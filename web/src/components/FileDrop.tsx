// A place a file can be dropped on. It shows itself as soon as a file is dragged into the
// window, before the pointer reaches it, and says what a drop there does. A file let go beside
// it is not opened by the browser in the app's place. What is dropped is checked after the
// drop, when its name can be read: one the place has no use for is said so, and nothing is taken.
import { Upload } from "lucide-react";
import { useEffect, useRef, useState, type DragEvent, type ReactNode } from "react";
import { useHouse } from "../store";

const carriesFiles = (e: { dataTransfer: DataTransfer | null }) => Boolean(e.dataTransfer && Array.from(e.dataTransfer.types).includes("Files"));

export function FileDrop({
  onFiles,
  accepts,
  label,
  refusal,
  one,
  disabled,
  className,
  children,
}: {
  onFiles: (files: File[]) => void;
  accepts: (file: File) => boolean;
  // What a drop here does, said while a file is over the window.
  label: string;
  // What is said when nothing dropped is of use here.
  refusal: string;
  // The place takes one file: the first of use.
  one?: boolean;
  disabled?: boolean;
  className?: string;
  children: ReactNode;
}) {
  // A drag fires enter and leave for every element it crosses, so both are counted: the drag
  // has left only when the count is back at nothing.
  const inWindow = useRef(0);
  const inPlace = useRef(0);
  const place = useRef<HTMLDivElement>(null);
  const [near, setNear] = useState(false);
  const [over, setOver] = useState(false);

  useEffect(() => {
    if (disabled) return;
    const rest = () => {
      inWindow.current = 0;
      inPlace.current = 0;
      setNear(false);
      setOver(false);
    };
    const enter = (e: DragEvent | globalThis.DragEvent) => {
      if (!carriesFiles(e)) return;
      inWindow.current += 1;
      setNear(true);
    };
    const leave = (e: globalThis.DragEvent) => {
      if (!carriesFiles(e)) return;
      inWindow.current = Math.max(0, inWindow.current - 1);
      if (inWindow.current === 0) rest();
    };
    const hover = (e: globalThis.DragEvent) => {
      if (!carriesFiles(e)) return;
      e.preventDefault(); // or the browser opens the file where the app is
      if (e.dataTransfer && !place.current?.contains(e.target as Node)) e.dataTransfer.dropEffect = "none";
    };
    const drop = (e: globalThis.DragEvent) => {
      if (carriesFiles(e)) e.preventDefault();
      rest();
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", hover);
    window.addEventListener("drop", drop);
    window.addEventListener("dragend", rest);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("dragover", hover);
      window.removeEventListener("drop", drop);
      window.removeEventListener("dragend", rest);
      rest();
    };
  }, [disabled]);

  const take = (e: DragEvent<HTMLDivElement>) => {
    if (disabled || !carriesFiles(e)) return;
    e.preventDefault();
    const dropped = Array.from(e.dataTransfer.files);
    const wanted = dropped.filter(accepts);
    const say = useHouse.getState().say;
    if (wanted.length === 0) return say(refusal);
    if (one && wanted.length > 1) say(`Took ${wanted[0].name}. One file at a time here.`);
    onFiles(one ? wanted.slice(0, 1) : wanted);
  };

  return (
    <div
      ref={place}
      className={`drop${className ? ` ${className}` : ""}`}
      data-near={near || undefined}
      data-over={over || undefined}
      onDragEnter={(e) => {
        if (disabled || !carriesFiles(e)) return;
        inPlace.current += 1;
        setOver(true);
      }}
      onDragLeave={(e) => {
        if (disabled || !carriesFiles(e)) return;
        inPlace.current = Math.max(0, inPlace.current - 1);
        if (inPlace.current === 0) setOver(false);
      }}
      onDragOver={(e) => {
        if (disabled || !carriesFiles(e)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
      }}
      onDrop={take}
    >
      {children}
      {near && (
        <div className="drop-veil" aria-hidden="true">
          <Upload />
          <span>{label}</span>
        </div>
      )}
    </div>
  );
}
