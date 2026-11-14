import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 break-words rounded-btn text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-green disabled:pointer-events-none disabled:opacity-60",
  {
    variants: {
      variant: {
        default: "bg-green text-white hover:bg-green/90",
        outline: "border border-line bg-white text-ink hover:bg-surface",
        ghost: "text-ink hover:bg-green-tint/50",
      },
      size: {
        default: "h-11 px-5",
        /** Phone primary action — 60px tall per design tokens (grows to fit 2 lines). */
        tall: "min-h-[60px] px-6 py-3 text-base",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends
    React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button
      className={cn(buttonVariants({ variant, size, className }))}
      ref={ref}
      {...props}
    />
  ),
);
Button.displayName = "Button";

export { Button, buttonVariants };
