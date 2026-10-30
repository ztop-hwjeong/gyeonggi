"use client";

import { CheckIcon, ListIcon } from "@phosphor-icons/react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { useCallback, useState } from "react";

export type ChoiceOption = {
  value: string;
  label: string;
  disabled?: boolean;
};

type ChoiceProps = {
  id?: string;
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  options: ChoiceOption[];
  placeholder?: string;
  disabled?: boolean;
  required?: boolean;
  className?: string;
};

export function SelectField({
  id,
  label,
  value,
  onValueChange,
  options,
  placeholder = "선택",
  disabled,
  required,
  className = "",
}: ChoiceProps) {
  const [container, setContainer] = useState<HTMLElement | null>(null);
  const triggerRef = useCallback((node: HTMLButtonElement | null) => {
    // 네이티브 대화상자의 최상위 레이어 안에 선택 목록 유지
    setContainer(node?.closest("dialog") ?? null);
  }, []);
  const selected = options.find((option) => option.value === value);
  return (
    <SelectPrimitive.Root
      value={selected ? `choice:${selected.value}` : ""}
      onValueChange={(next) => onValueChange(next.slice("choice:".length))}
      disabled={disabled}
      required={required}
    >
      <SelectPrimitive.Trigger
        ref={triggerRef}
        id={id}
        aria-label={label}
        title={selected?.label}
        className={`choice-trigger ${className}`}
      >
        <SelectPrimitive.Value placeholder={placeholder}>
          {selected?.label}
        </SelectPrimitive.Value>
        <SelectPrimitive.Icon className="choice-icon">
          <ListIcon size={14} aria-hidden="true" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal container={container}>
        <SelectPrimitive.Content
          className="choice-content"
          position="popper"
          sideOffset={5}
          align="start"
        >
          <SelectPrimitive.Viewport className="choice-viewport">
            {options.map((option) => (
              <SelectPrimitive.Item
                key={option.value}
                value={`choice:${option.value}`}
                data-choice-value={option.value}
                disabled={option.disabled}
                className="choice-option"
              >
                <SelectPrimitive.ItemText>
                  {option.label}
                </SelectPrimitive.ItemText>
                <SelectPrimitive.ItemIndicator className="choice-check">
                  <CheckIcon size={15} aria-hidden="true" />
                </SelectPrimitive.ItemIndicator>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}

export function ChoiceGroup({
  label,
  value,
  onValueChange,
  options,
  disabled,
  className = "",
}: ChoiceProps) {
  return (
    <fieldset aria-label={label} className={`choice-group ${className}`}>
      {options.map((option) => (
        <button
          type="button"
          key={option.value}
          aria-pressed={value === option.value}
          disabled={disabled || option.disabled}
          onClick={() => onValueChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </fieldset>
  );
}
