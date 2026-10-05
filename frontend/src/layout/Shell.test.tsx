import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Inbox, Zap } from "lucide-react";
import { renderWithProviders } from "../test/render";
import { ShellProvider, useShell } from "./shell";
import { Sidebar, type SideGroup } from "./Sidebar";
import { Topbar } from "./Topbar";

const groups: SideGroup[] = [
  { items: [{ to: "/", end: true, label: "nav.inbox", icon: <Inbox size={18} />, badge: 3 }] },
  {
    label: "nav.groups.product",
    items: [{ to: "/ems", label: "nav.ems", icon: <Zap size={18} />, badge: 2, badgeTone: "neg" }],
  },
];

function PaletteState() {
  const { paletteOpen, assistantOpen } = useShell();
  return <output>{`palette:${paletteOpen} assistant:${assistantOpen}`}</output>;
}

describe("app shell", () => {
  it("renders grouped navigation with badges and the active section", () => {
    renderWithProviders(
      <ShellProvider>
        <Sidebar groups={groups} />
      </ShellProvider>,
      { route: "/ems?tab=alerts" },
    );
    expect(screen.getByText("Продукт")).toBeInTheDocument();
    const ems = screen.getByRole("link", { name: /События/ });
    expect(ems).toHaveAttribute("aria-current", "page");
    expect(ems).toHaveTextContent("2");
    expect(screen.getByRole("link", { name: /Входящие/ })).not.toHaveAttribute("aria-current");
  });

  it("collapses the sidebar and remembers it", async () => {
    const { unmount } = renderWithProviders(
      <ShellProvider>
        <Sidebar groups={groups} />
      </ShellProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Свернуть меню" }));
    unmount();
    renderWithProviders(
      <ShellProvider>
        <Sidebar groups={groups} />
      </ShellProvider>,
    );
    expect(screen.getByRole("button", { name: "Развернуть меню" })).toBeInTheDocument();
  });

  it("opens the palette and the assistant from the keyboard and switches language and theme", async () => {
    renderWithProviders(
      <ShellProvider>
        <Topbar />
        <PaletteState />
      </ShellProvider>,
    );
    await userEvent.keyboard("{Control>}k{/Control}");
    expect(screen.getByRole("status")).toHaveTextContent("palette:true assistant:false");
    await userEvent.keyboard("{Control>}j{/Control}");
    expect(screen.getByRole("status")).toHaveTextContent("assistant:true");
    await userEvent.click(screen.getByRole("button", { name: /Язык/ }));
    expect(screen.getByRole("button", { name: /Search pages/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Theme/ }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
