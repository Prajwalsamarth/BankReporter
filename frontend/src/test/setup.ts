import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// Mantine needs these browser APIs, which jsdom lacks.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false, media: query, onchange: null,
    addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  }),
});
class ResizeObserverStub { observe() {} unobserve() {} disconnect() {} }
window.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
window.HTMLElement.prototype.scrollIntoView = () => {};
