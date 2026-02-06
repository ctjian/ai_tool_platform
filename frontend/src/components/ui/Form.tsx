import { ReactNode } from 'react';

interface FormProps {
  onSubmit: (e: React.FormEvent) => void;
  children: ReactNode;
  className?: string;
}

export const Form = ({ onSubmit, children, className = '' }: FormProps) => (
  <form onSubmit={onSubmit} className={`space-y-4 ${className}`}>
    {children}
  </form>
);

interface FormGroupProps {
  children: ReactNode;
  className?: string;
}

export const FormGroup = ({ children, className = '' }: FormGroupProps) => (
  <div className={`space-y-2 ${className}`}>{children}</div>
);

interface FormLabelProps {
  children: ReactNode;
  htmlFor?: string;
  required?: boolean;
}

export const FormLabel = ({ children, htmlFor, required }: FormLabelProps) => (
  <label htmlFor={htmlFor} className="block text-sm font-medium text-gray-700">
    {children}
    {required && <span className="text-red-500 ml-1">*</span>}
  </label>
);
