import { useMemo, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  BarChart3,
  BookOpen,
  ChevronDown,
  ClipboardList,
  FileText,
  Inbox,
  LogOut,
  Table2,
  TriangleAlert,
  Users,
} from "lucide-react";
import { initials } from "@/features/auth/types";
import { useSessionStore } from "@/stores/session";
import { cn } from "@/lib/utils";

interface NavItem {
  to: string;
  labelKey: string;
  icon: ReactNode;
  end?: boolean;
}

/** /manager — sidebar layout per manager-web.pdf (248px sidebar, main content area). */
export default function ManagerLayout() {
  const { t } = useTranslation();
  const profile = useSessionStore((s) => s.profile);
  const signOut = useSessionStore((s) => s.signOut);
  const location = useLocation();

  const mainNav: NavItem[] = useMemo(
    () => [
      {
        to: "/manager",
        labelKey: "manager.reviewQueue",
        icon: <Inbox className="h-4.5 w-4.5" />,
        end: true,
      },
      {
        to: "/manager/escalations",
        labelKey: "manager.escalations",
        icon: <TriangleAlert className="h-4.5 w-4.5" />,
      },
      {
        to: "/manager/knowledge",
        labelKey: "manager.knowledgeBase",
        icon: <BookOpen className="h-4.5 w-4.5" />,
      },
      {
        to: "/manager/analytics",
        labelKey: "manager.analytics",
        icon: <BarChart3 className="h-4.5 w-4.5" />,
      },
      {
        to: "/manager/team",
        labelKey: "manager.team",
        icon: <Users className="h-4.5 w-4.5" />,
      },
    ],
    [],
  );

  const setupNav: NavItem[] = useMemo(
    () => [
      {
        to: "/manager/setup/machines",
        labelKey: "manager.machines",
        icon: <ClipboardList className="h-4.5 w-4.5" />,
      },
      {
        to: "/manager/setup/documents",
        labelKey: "manager.documents",
        icon: <FileText className="h-4.5 w-4.5" />,
      },
      {
        to: "/manager/setup/logs",
        labelKey: "manager.breakdownLogs",
        icon: <Table2 className="h-4.5 w-4.5" />,
      },
      {
        to: "/manager/setup/people",
        labelKey: "manager.people",
        icon: <Users className="h-4.5 w-4.5" />,
      },
    ],
    [],
  );

  const inSetup = location.pathname.startsWith("/manager/setup");

  return (
    <div className="flex min-h-screen bg-enamel">
      {/* Sidebar — 248px */}
      <aside className="flex w-[248px] shrink-0 flex-col border-r border-line bg-surface px-4 py-6">
        {/* Wordmark */}
        <div className="flex items-center gap-2 px-2">
          <span className="h-2.5 w-2.5 rounded-full bg-green-deep" />
          <span className="font-head text-lg font-bold text-green-deep">
            {t("login.wordmark")}
          </span>
        </div>

        {/* Plant card */}
        <button
          type="button"
          className="mt-6 flex w-full items-center justify-between rounded-xl border border-line bg-white px-4 py-3 text-left hover:bg-enamel/50"
        >
          <span>
            <span className="block text-sm font-semibold text-ink">
              {profile?.tenant.name ?? "—"}
            </span>
            <span className="block text-xs text-ink-muted">
              Pune · 4 machines
            </span>
          </span>
          <ChevronDown className="h-4 w-4 text-ink-faint" />
        </button>

        {/* Main nav */}
        <nav className="mt-6 flex flex-col gap-1">
          {mainNav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium",
                  isActive
                    ? "border border-line bg-white text-ink shadow-sm"
                    : "text-ink-muted hover:bg-white/60 hover:text-ink",
                )
              }
            >
              {item.icon}
              {t(item.labelKey)}
            </NavLink>
          ))}
        </nav>

        {/* Setup group — admin only */}
        {profile?.is_admin && (
          <>
            <p
              className={cn(
                "mb-1 mt-7 px-3 text-xs font-medium uppercase tracking-wide text-ink-faint",
                inSetup && "text-ink-muted",
              )}
            >
              {t("manager.setup")}
            </p>
            <nav className="flex flex-col gap-1">
              {setupNav.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium",
                      isActive
                        ? "border border-line bg-white text-ink shadow-sm"
                        : "text-ink-muted hover:bg-white/60 hover:text-ink",
                    )
                  }
                >
                  {item.icon}
                  {t(item.labelKey)}
                </NavLink>
              ))}
            </nav>
          </>
        )}

        {/* User card */}
        <div className="mt-auto flex items-center gap-3 rounded-xl px-2 py-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-green-tint text-xs font-bold text-green-deep">
            {initials(profile?.name ?? "")}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-ink">
              {profile?.name}
            </p>
            <p className="text-xs text-ink-muted">
              {t("manager.supervisor")}
              {profile?.is_admin ? ` · ${t("manager.admin")}` : ""}
            </p>
          </div>
          <button
            type="button"
            aria-label={t("manager.signOut")}
            onClick={() => void signOut()}
            className="text-ink-faint hover:text-ink"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </aside>

      {/* Main area */}
      <main className="flex-1 px-10 py-8 xl:px-14">
        <Outlet />
      </main>
    </div>
  );
}
