// Registers @testing-library/jest-dom matchers AND augments vitest's `expect`
// type so `toBeInTheDocument` etc. are recognized by both the runner and tsc.
import "@testing-library/jest-dom/vitest";
