import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConnectionForm } from "./ConnectionForm";
import { renderWithProviders } from "../test/render";

const existing = {
  id: 1, name: "NovaBank", dialect: "postgresql" as const, schemas: ["los"], needs_password: false,
  url_masked: "postgresql+psycopg://novabank:***@localhost:5433/novabank", client: null,
};

describe("ConnectionForm", () => {
  it("creates a connection with all fields", async () => {
    const onSubmit = vi.fn();
    renderWithProviders(<ConnectionForm onSubmit={onSubmit} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Name"), "Bharat");
    await user.click(screen.getByRole("radio", { name: "MySQL" }));
    await user.clear(screen.getByLabelText("Host"));
    await user.type(screen.getByLabelText("Host"), "db.local");
    await user.clear(screen.getByLabelText("Port"));
    await user.type(screen.getByLabelText("Port"), "3307");
    await user.type(screen.getByLabelText("Database"), "bfs_core");
    await user.type(screen.getByLabelText("User"), "bfs");
    await user.type(screen.getByLabelText("Password"), "secret");
    await user.type(screen.getByRole("textbox", { name: "Schemas" }), "bfs_core{enter}");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).toHaveBeenCalledWith({
      name: "Bharat", dialect: "mysql", host: "db.local", port: 3307, database: "bfs_core",
      user: "bfs", password: "secret", schemas: ["bfs_core"],
    });
  });

  it("requires a password when creating", async () => {
    const onSubmit = vi.fn();
    renderWithProviders(<ConnectionForm onSubmit={onSubmit} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Name"), "x");
    await user.type(screen.getByLabelText("Database"), "d");
    await user.type(screen.getByLabelText("User"), "u");
    await user.type(screen.getByRole("textbox", { name: "Schemas" }), "s{enter}");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("Password is required")).toBeInTheDocument();
  });

  it("never pre-fills the password when editing and sends null when left blank", async () => {
    const onSubmit = vi.fn();
    renderWithProviders(<ConnectionForm initial={existing} onSubmit={onSubmit} />);
    const password = screen.getByLabelText("Password") as HTMLInputElement;
    expect(password.value).toBe("");
    expect(password.placeholder).toBe("leave blank to keep");
    expect(screen.getByLabelText("Name")).toHaveValue("NovaBank");
    expect(screen.getByLabelText("Host")).toHaveValue("localhost");
    expect(screen.getByLabelText("Port")).toHaveValue("5433");
    expect(screen.getByLabelText("User")).toHaveValue("novabank");
    await userEvent.setup().click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ password: null, schemas: ["los"] }));
  });
  it("asks the admin which client the connection belongs to", async () => {
    const onSubmit = vi.fn();
    renderWithProviders(<ConnectionForm initial={existing} onSubmit={onSubmit}
      clients={[{ id: 1, name: "NovaBank" }, { id: 2, name: "Bharat Finserv" }]} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("Choose a client")).toBeInTheDocument();
    await user.click(screen.getByRole("textbox", { name: "Client" }));
    await user.click(await screen.findByRole("option", { name: "Bharat Finserv" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ client_id: 2 }));
  });
});
