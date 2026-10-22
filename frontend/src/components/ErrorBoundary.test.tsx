import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";
import { renderWithProviders } from "../test/render";

function Boom(): never {
  throw new Error("kaboom");
}

describe("ErrorBoundary", () => {
  it("shows a message instead of a blank page when a child crashes", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderWithProviders(<ErrorBoundary><Boom /></ErrorBoundary>);
    expect(screen.getByText("Something went wrong on this page")).toBeInTheDocument();
    expect(screen.getByText("kaboom")).toBeInTheDocument();
  });
});
