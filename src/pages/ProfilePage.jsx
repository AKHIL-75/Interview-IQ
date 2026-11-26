import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { User, Mail, Briefcase, Code, GraduationCap, Save, Edit3, Loader2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import Card from '../components/Card';
import Button from '../components/Button';
import SkillBadge from '../components/SkillBadge';

export default function ProfilePage() {
  const { user, updateProfile } = useAuth();
  const { success, error: showError } = useToast();
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);

  // Build form state from user object
  const buildFormFromUser = useCallback((u) => ({
    name: u?.name || '',
    targetRole: u?.targetRole || 'Software Engineer',
    experience: u?.experience || 'Fresher',
    skills: u?.skills || [],
  }), []);

  const [form, setForm] = useState(() => buildFormFromUser(user));

  // Re-sync form when user object changes (e.g., profile fetched after login)
  useEffect(() => {
    if (!editing && user) {
      setForm(buildFormFromUser(user));
    }
  }, [user, editing, buildFormFromUser]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateProfile(form);
      setEditing(false);
      success('Profile updated successfully!');
    } catch (err) {
      showError(err?.message || 'Failed to update profile. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setForm(buildFormFromUser(user));
    setEditing(false);
  };

  // Email is managed by Supabase Auth — display read-only
  const displayEmail = user?.email || '';
  const displayInitial = (form.name || displayEmail || '?').charAt(0).toUpperCase();

  return (
    <div className="content-area animate-fade-in">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-semibold text-heading">Profile</h1>
          <div className="flex items-center gap-2">
            {editing && (
              <Button
                variant="secondary"
                onClick={handleCancel}
                size="sm"
                disabled={saving}
              >
                Cancel
              </Button>
            )}
            <Button
              variant={editing ? 'primary' : 'secondary'}
              icon={saving ? Loader2 : editing ? Save : Edit3}
              onClick={editing ? handleSave : () => setEditing(true)}
              size="sm"
              loading={saving}
              disabled={saving}
            >
              {saving ? 'Saving...' : editing ? 'Save Changes' : 'Edit Profile'}
            </Button>
          </div>
        </div>

        {/* Avatar */}
        <Card className="flex flex-col items-center py-8 mb-6">
          <div className="w-16 h-16 rounded-lg bg-selected flex items-center justify-center mb-4 border border-line">
            <span className="text-3xl font-semibold text-primary">
              {displayInitial}
            </span>
          </div>
          <h2 className="text-xl font-semibold text-heading">{form.name || displayEmail}</h2>
          <p className="text-secondary text-sm">{displayEmail}</p>
        </Card>

        {/* Profile Details */}
        <div className="space-y-4">
          <Card>
            <label htmlFor="profile-name-input" className="block text-sm font-medium text-secondary mb-2">
              <div className="flex items-center gap-2 mb-2">
                <User className="w-4 h-4 text-primary" />
                Full Name
              </div>
            </label>
            {editing ? (
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="input-field"
                id="profile-name-input"
              />
            ) : (
              <p className="text-heading">{form.name || '—'}</p>
            )}
          </Card>

          <Card>
            <label className="block text-sm font-medium text-secondary mb-2">
              <div className="flex items-center gap-2 mb-2">
                <Mail className="w-4 h-4 text-primary" />
                Email
              </div>
            </label>
            {/* Email is managed by Supabase Auth — always read-only */}
            <p className="text-heading">{displayEmail}</p>
            {editing && (
              <p className="text-xs text-secondary mt-1">
                Email is managed by your authentication provider and cannot be changed here.
              </p>
            )}
          </Card>

          <Card>
            <label htmlFor="profile-target-role-input" className="block text-sm font-medium text-secondary mb-2">
              <div className="flex items-center gap-2 mb-2">
                <Briefcase className="w-4 h-4 text-primary" />
                Target Role
              </div>
            </label>
            {editing ? (
              <input
                type="text"
                value={form.targetRole}
                onChange={(e) => setForm({ ...form, targetRole: e.target.value })}
                className="input-field"
                id="profile-target-role-input"
              />
            ) : (
              <p className="text-heading">{form.targetRole}</p>
            )}
          </Card>

          <Card>
            <label htmlFor="profile-experience-select" className="block text-sm font-medium text-secondary mb-2">
              <div className="flex items-center gap-2 mb-2">
                <GraduationCap className="w-4 h-4 text-primary" />
                Experience Level
              </div>
            </label>
            {editing ? (
              <select
                value={form.experience}
                onChange={(e) => setForm({ ...form, experience: e.target.value })}
                className="input-field"
                id="profile-experience-select"
              >
                <option value="Fresher">Fresher</option>
                <option value="1-2 years">1-2 years</option>
                <option value="3-5 years">3-5 years</option>
                <option value="5+ years">5+ years</option>
              </select>
            ) : (
              <p className="text-heading">{form.experience}</p>
            )}
          </Card>

          <Card>
            <label className="block text-sm font-medium text-secondary mb-2">
              <div className="flex items-center gap-2 mb-2">
                <Code className="w-4 h-4 text-primary" />
                Skills
              </div>
            </label>
            <div className="flex flex-wrap gap-2">
              {(form.skills && form.skills.length > 0) ? (
                form.skills.map((skill) => (
                  <SkillBadge key={skill} skill={skill} />
                ))
              ) : (
                <p className="text-secondary text-sm">No skills added yet</p>
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
