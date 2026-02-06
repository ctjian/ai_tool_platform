import { useState } from 'react';

interface SliderProps {
  label?: string;
  min: number;
  max: number;
  step?: number;
  value: number;
  onChange: (value: number) => void;
  showValue?: boolean;
}

export const Slider = ({
  label,
  min,
  max,
  step = 0.1,
  value,
  onChange,
  showValue = true,
}: SliderProps) => {
  return (
    <div className="w-full">
      {label && (
        <div className="flex justify-between items-center mb-2">
          <label className="block text-sm font-medium text-gray-700">{label}</label>
          {showValue && <span className="text-sm font-semibold text-indigo-600">{value.toFixed(2)}</span>}
        </div>
      )}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-indigo-500"
      />
    </div>
  );
};
