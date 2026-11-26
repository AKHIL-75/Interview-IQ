import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { supabase, setGlobalAccessToken, getAuthProviderSettings } from '../lib/supabase';

import { initialAuthCallback, hasRecoveryMarker, clearRecoveryMarker, requestPasswordReset, startGoogleSignIn, callbackUrl } from '../services/authFlows';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [recoveryActive, setRecoveryActive] = useState(() =>
    (initialAuthCallback.kind === 'recovery' && !initialAuthCallback.tokenHash) || hasRecoveryMarker(window.sessionStorage));

  /**
   * Build a user object that matches the existing API surface consumed
   * by 10+ components: { id, name, email, targetRole, experience, skills, avatar }
   */
  const buildUserObject = useCallback((authUser, profile) => {
    return {
      id: authUser.id,
      email: authUser.email,
      name: profile?.full_name || authUser.user_metadata?.full_name || authUser.email,
      targetRole: profile?.target_role || 'Software Engineer',
      experience: profile?.experience || 'Fresher',
      skills: profile?.skills || [],
      avatar: profile?.avatar_url || null,
    };
  }, []);

  /**
   * Fetch the user's profile from the profiles table.
   * Falls back gracefully if profile hasn't been created yet.
   */
  const fetchProfile = useCallback(async (userId) => {
    if (!userId) return null;
    try {
      const { data, error } = await supabase
        .from('profiles')
        .select('*')
        .eq('id', userId)
        .maybeSingle();

      if (error) {
        console.warn('[AuthContext] Error fetching profile:', error.message);
      }
      return data || null;
    } catch (err) {
      console.warn('[AuthContext] Failed to fetch profile:', err);
      return null;
    }
  }, []);

  // SDK listeners must return synchronously; profile requests run after its lock releases.
  useEffect(() => {
    let mounted = true;
    let generation = 0;
    const timers = new Set();
    const apply = (activeSession) => {
      if (!mounted) return;
      const current = ++generation;
      setSession(activeSession);
      setGlobalAccessToken(activeSession?.access_token || null);
      setUser(activeSession?.user ? buildUserObject(activeSession.user, null) : null);
      setLoading(false);
      if (activeSession?.user) {
        const timer = setTimeout(async () => {
          timers.delete(timer);
          const profile = await fetchProfile(activeSession.user.id);
          if (mounted && generation === current) setUser(buildUserObject(activeSession.user, profile));
        }, 0);
        timers.add(timer);
      }
    };
    const beforeRestore = generation;
    supabase.auth.getSession().then(({ data, error }) => {
      if (mounted && generation === beforeRestore) apply(error ? null : data?.session || null);
    }).catch(() => { if (mounted && generation === beforeRestore) apply(null); });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, newSession) => {
      if (!mounted) return;
      if (event === 'PASSWORD_RECOVERY') setRecoveryActive(true);
      if (event === 'SIGNED_OUT') {
        setRecoveryActive(false);
        clearRecoveryMarker(window.sessionStorage);
        try {
          localStorage.removeItem('interviewiq_user');
          localStorage.removeItem('interviewiq_history');
        } catch { /* Storage may be unavailable. */ }
      }
      apply(newSession || null);
    });
    return () => {
      mounted = false;
      generation++;
      subscription.unsubscribe();
      timers.forEach(clearTimeout);
    };
  }, [fetchProfile, buildUserObject]);

  const requestReset = useCallback((email) => requestPasswordReset(supabase.auth, email, window.location.origin), []);
  const loginWithGoogle = useCallback(() => startGoogleSignIn(supabase.auth, window.location.origin, getAuthProviderSettings), []);
  const endRecovery = useCallback(() => {
    clearRecoveryMarker(window.sessionStorage);
    setRecoveryActive(false);
  }, []);

  // ─── login ──────────────────────────────────────────────────────
  const login = useCallback(async (email, password) => {
    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (error) throw error;

    if (data.session) {
      setSession(data.session);
      setGlobalAccessToken(data.session.access_token);
    }

    const profile = await fetchProfile(data.user.id);
    const userData = buildUserObject(data.user, profile);
    setUser(userData);
    return userData;
  }, [fetchProfile, buildUserObject]);

  // ─── register ───────────────────────────────────────────────────
  const register = useCallback(async (name, email, password) => {
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: { full_name: name },
        emailRedirectTo: callbackUrl(window.location.origin, '/'),
      },
    });

    if (error) throw error;

    if (data.session) {
      setSession(data.session);
      setGlobalAccessToken(data.session.access_token);
    }

    // The handle_new_user trigger creates the profile row.
    // Give the trigger a moment, then fetch the profile.
    if (data.user) {
      // Small delay to allow the database trigger to fire
      await new Promise(resolve => setTimeout(resolve, 300));
      const profile = await fetchProfile(data.user.id);
      const userData = buildUserObject(data.user, profile);
      if (data.session) setUser(userData);
      return { ...userData, confirmationRequired: !data.session };
    }

    return null;
  }, [fetchProfile, buildUserObject]);

  // ─── logout ─────────────────────────────────────────────────────
  const logout = useCallback(async () => {
    await supabase.auth.signOut();
    setSession(null);
    setGlobalAccessToken(null);
    setUser(null);
    // Clean up localStorage interview data on logout
    try {
      localStorage.removeItem('interviewiq_user');
      localStorage.removeItem('interviewiq_history');
    } catch {
      // ignore
    }
  }, []);



  // ─── updateProfile ──────────────────────────────────────────────
  const updateProfile = useCallback(async (data) => {
    if (!user?.id) {
      throw new Error('User not authenticated');
    }

    const updates = {};
    if (data.name !== undefined) updates.full_name = data.name;
    if (data.targetRole !== undefined) updates.target_role = data.targetRole;
    if (data.experience !== undefined) updates.experience = data.experience;
    if (data.skills !== undefined) updates.skills = data.skills;
    if (data.avatar !== undefined) updates.avatar_url = data.avatar;

    if (Object.keys(updates).length > 0) {
      updates.updated_at = new Date().toISOString();
      const { error } = await supabase
        .from('profiles')
        .upsert({ id: user.id, ...updates });

      if (error) {
        console.error('[AuthContext] Profile update error:', error.message);
        throw error;
      }
    }

    // Update local state immediately (safely only updating profile fields)
    const updated = {
      ...user,
      ...(data.name !== undefined ? { name: data.name } : {}),
      ...(data.targetRole !== undefined ? { targetRole: data.targetRole } : {}),
      ...(data.experience !== undefined ? { experience: data.experience } : {}),
      ...(data.skills !== undefined ? { skills: data.skills } : {}),
      ...(data.avatar !== undefined ? { avatar: data.avatar } : {}),
    };
    setUser(updated);
    return updated;
  }, [user]);

  return (
    <AuthContext.Provider value={{ user, session, loading, recoveryActive, requestReset, loginWithGoogle, endRecovery, login, register, logout, updateProfile }}>
      {children}
    </AuthContext.Provider>
  );

}

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
};

/**
 * Convenience hook for Phase 13+ analytics, history, and dashboard components.
 * Provides direct access to user identity, validated user ID, and auth status
 * without duplicating auth contexts.
 */
export const useCurrentUser = () => {
  const { user, loading } = useAuth();
  return {
    user,
    userId: user?.id || null,
    isAuthenticated: Boolean(user?.id),
    loading,
  };
};
