import { useEffect, useRef, useState } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "cn";

// One line cut with dots when it doesn't fit; the full text in a tooltip on
// hover - only when it was cut (measured ahead, so the first hover opens it).
export function TruncatedText({ text, className }: { text: string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [cut, setCut] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) {
      return;
    }
    const measure = () => {
      setCut(el.scrollWidth > el.clientWidth);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => {
      observer.disconnect();
    };
  }, [text]);
  return (
    <Tooltip disabled={!cut}>
      <TooltipTrigger render={<span ref={ref} />} className={cn("block truncate", className)}>
        {text}
      </TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </Tooltip>
  );
}
