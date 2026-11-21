import { useId, useState, type ReactNode } from "react";
import { Check, ChevronsUpDown, Search } from "lucide-react";
import { Command } from "cmdk";
import { Popover, PopoverTrigger, PopoverContent } from "./popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./select";

type Option = {
  value: string;
  label: string;
  disabled?: boolean;
  description?: string;
  icon?: ReactNode;
};
type Props = {
  label: string;
  options: readonly Option[];
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  className?: string;
  error?: string;
};

function Choice({
  option,
  detailed = false,
}: {
  option?: Option;
  detailed?: boolean;
}) {
  return (
    <span className="choice-value">
      {option?.icon}
      <span className="choice-text">
        {option?.label}
        {detailed && option?.description && <small>{option.description}</small>}
      </span>
    </span>
  );
}

export function ChoiceField({
  label,
  options,
  value,
  onChange,
  disabled,
  error,
  className = "",
}: Props) {
  const id = useId();
  return (
    <div className={"choice-field " + className}>
      <label id={id + "-label"} htmlFor={id}>
        {label}
      </label>
      <Select value={value} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger id={id} aria-labelledby={id + "-label"}>
          <SelectValue>
            <Choice option={options.find((o) => o.value === value)} />
          </SelectValue>
        </SelectTrigger>
        <SelectContent position="popper" sideOffset={4}>
          {options.map((option) => (
            <SelectItem
              key={option.value}
              value={option.value}
              disabled={option.disabled}
              textValue={option.label}
            >
              <Choice option={option} detailed />
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {error && <small role="alert">{error}</small>}
    </div>
  );
}

export function SearchChoice({ label, options, value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="choice-field">
      <label id={id + "-label"} htmlFor={id}>
        {label}
      </label>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            id={id}
            type="button"
            role="combobox"
            aria-expanded={open}
            aria-haspopup="dialog"
            aria-labelledby={id + "-label " + id + "-value"}
            className="choice-search-trigger"
          >
            <span id={id + "-value"}>
              {options.find((o) => o.value === value)?.label}
            </span>
            <ChevronsUpDown size={14} />
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" aria-label={label}>
          <Command label={label}>
            <div className="choice-search">
              <Search size={15} />
              <Command.Input
                aria-label={"Search " + label}
                placeholder="Search people…"
              />
            </div>
            <Command.List>
              <Command.Empty>No matches</Command.Empty>
              {options.map((option) => (
                <Command.Item
                  key={option.value}
                  value={option.value || "everyone"}
                  keywords={[option.label]}
                  onSelect={() => {
                    setOpen(false);
                    onChange(option.value);
                  }}
                >
                  {option.label}
                  {value === option.value && <Check size={14} />}
                </Command.Item>
              ))}
            </Command.List>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}
