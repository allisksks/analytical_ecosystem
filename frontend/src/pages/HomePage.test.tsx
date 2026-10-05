import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Topbar } from "../layout/Topbar";
import { renderWithProviders } from "../test/render";
import { HomePage } from "./HomePage";

describe("HomePage", () => {
  it("shows module cards in Russian by default", () => {
    renderWithProviders(<HomePage />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Аналитическая платформа");
    expect(screen.getByRole("link", { name: /База знаний/ })).toHaveAttribute("href", "/kb");
  });

  it("switches language and theme from the top bar", async () => {
    renderWithProviders(
      <>
        <Topbar />
        <HomePage />
      </>,
    );
    await userEvent.click(screen.getByRole("button", { name: /Язык/ }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Analytics Platform");
    await userEvent.click(screen.getByRole("button", { name: /Theme/ }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
