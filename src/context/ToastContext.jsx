import { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react';

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const [placement, setPlacement] = useState('default');
  const placementRef = useRef(placement); placementRef.current = placement;
  const timers = useRef(new Map());
  useEffect(() => () => { timers.current.forEach(clearTimeout); timers.current.clear(); }, []);

  const addToast = useCallback((message, type = 'info', options) => {
    const { action, duration = placementRef.current === 'immersive' ? 6000 : 3000 } = typeof options === 'number' ? { duration: options } : options || {};
    const id = Date.now() + Math.random();
    setToasts(prev => [...prev, { id, message, type, action }]);
    timers.current.set(id, setTimeout(() => {
      timers.current.delete(id);
      setToasts(prev => prev.filter(t => t.id !== id));
    }, duration));
    return id;
  }, []);

  const removeToast = useCallback((id) => {
    clearTimeout(timers.current.get(id)); timers.current.delete(id);
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const success = useCallback((msg, options) => addToast(msg, 'success', options), [addToast]);
  const error = useCallback((msg, options) => addToast(msg, 'error', options), [addToast]);
  const info = useCallback((msg, options) => addToast(msg, 'info', options), [addToast]);

  return (
    <ToastContext.Provider value={{ toasts, addToast, removeToast, success, error, info, placement, setPlacement }}>
      {children}
    </ToastContext.Provider>
  );
}

export const useToast = () => {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
};
export const useOptionalToast = () => useContext(ToastContext);
