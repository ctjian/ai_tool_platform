import { useState, useEffect } from 'react';

export interface ToastMessage {
  id: string;
  message: string;
  type: 'success' | 'error' | 'info' | 'warning';
  duration?: number;
}

let toastQueue: ToastMessage[] = [];
let listeners: ((toasts: ToastMessage[]) => void)[] = [];

export const addToast = (message: string, type: 'success' | 'error' | 'info' | 'warning' = 'info', duration = 3000) => {
  const id = Date.now().toString();
  const toast: ToastMessage = { id, message, type, duration };
  toastQueue.push(toast);
  notifyListeners();

  if (duration > 0) {
    setTimeout(() => {
      removeToast(id);
    }, duration);
  }
};

const removeToast = (id: string) => {
  toastQueue = toastQueue.filter((t) => t.id !== id);
  notifyListeners();
};

const notifyListeners = () => {
  listeners.forEach((listener) => listener([...toastQueue]));
};

const subscribe = (listener: (toasts: ToastMessage[]) => void) => {
  listeners.push(listener);
  return () => {
    listeners = listeners.filter((l) => l !== listener);
  };
};

interface ToastContainerProps {
  position?: 'top-right' | 'top-left' | 'bottom-right' | 'bottom-left';
}

export const ToastContainer = ({ position = 'top-right' }: ToastContainerProps) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  useEffect(() => {
    return subscribe(setToasts);
  }, []);

  const positionClasses = {
    'top-right': 'top-4 right-4',
    'top-left': 'top-4 left-4',
    'bottom-right': 'bottom-4 right-4',
    'bottom-left': 'bottom-4 left-4',
  };

  return (
    <div className={`fixed ${positionClasses[position]} z-50 space-y-3 max-w-sm`}>
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`
            px-4 py-3 rounded-lg text-white font-medium shadow-lg
            animate-in fade-in slide-in-from-top-4 duration-300
            ${toast.type === 'success' ? 'bg-green-500' : ''}
            ${toast.type === 'error' ? 'bg-red-500' : ''}
            ${toast.type === 'info' ? 'bg-blue-500' : ''}
            ${toast.type === 'warning' ? 'bg-yellow-500' : ''}
          `}
        >
          {toast.message}
        </div>
      ))}
    </div>
  );
};
