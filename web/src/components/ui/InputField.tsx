import { useId, useRef, useState, type ComponentProps } from "react";
import { Check, Copy, Eye, EyeOff, LockKeyhole } from "lucide-react";
import { Input } from "./input";
import { Textarea } from "./textarea";

type LabelProps = { label: string; hint?: string; optional?: boolean; readOnly?: boolean };

function FieldLabel({
  id,
  label,
  hint,
  optional,
  readOnly,
}: LabelProps & { id: string }) {
  return (
    <div className="field-caption">
      <label htmlFor={id}>{label}</label>
      {readOnly && <small className="field-readonly"><LockKeyhole size={11} aria-hidden="true" />Read only</small>}
      {optional && !readOnly && <small>Optional</small>}
      {hint && <p id={id + "-hint"}>{hint}</p>}
    </div>
  );
}

export function InputField({
  label,
  hint,
  optional,
  copyable,
  type = "text",
  ...props
}: ComponentProps<"input"> & LabelProps & { copyable?: boolean }) {
  const id = useId();
  const field = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState(false);
  const [visible, setVisible] = useState(false);
  const [copiedValue, setCopiedValue] = useState("");
  const showCopied = copied && copiedValue === String(props.value);
  return (
    <div className="settings-input-row">
      <FieldLabel {...{ id, label, hint, optional }} readOnly={props.readOnly} />
      <div className="field-control">
        <Input
          {...props}
          id={id}
          ref={field}
          aria-describedby={hint ? id + "-hint" : undefined}
          type={type === "password" && visible ? "text" : type}
        />
        {copyable && (
          <button
            type="button"
            className="input-action"
            onClick={async () => {
              const text = field.current?.value ?? "";
              try {
                await navigator.clipboard.writeText(text);
                setCopiedValue(text);
                setCopied(true);
              } catch {
                field.current?.focus();
                field.current?.select();
                setCopied(false);
              }
            }}
          >
            {showCopied ? <Check size={13} /> : <Copy size={13} />}
            <span aria-live="polite">{showCopied ? "Copied" : "Copy"}</span>
          </button>
        )}
        {type === "password" && (
          <button
            type="button"
            disabled={props.disabled}
            className="input-action"
            aria-label={visible ? "Hide password" : "Show password"}
            aria-pressed={visible}
            onClick={() => setVisible(!visible)}
          >
            {visible ? <EyeOff size={15} /> : <Eye size={15} />}
          </button>
        )}
      </div>
    </div>
  );
}

export function TextareaField({
  label,
  optional,
  hint,
  ...props
}: ComponentProps<"textarea"> & LabelProps) {
  const id = useId();
  return (
    <div className="settings-input-row">
      <FieldLabel {...{ id, label, hint, optional }} readOnly={props.readOnly} />
      <Textarea
        {...props}
        id={id}
        aria-describedby={hint ? id + "-hint" : undefined}
      />
    </div>
  );
}
