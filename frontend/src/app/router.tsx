import { useEffect, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ToastViewport } from "@/components/ui/toast";
import { homeForRole, useSessionStore } from "@/stores/session";
import PhoneLogin from "@/features/auth/PhoneLogin";
import WebLogin from "@/features/auth/WebLogin";
import TechHome from "@/features/tech/TechHome";
import ManagerLayout from "@/features/manager/ManagerLayout";
import ManagerHome from "@/features/manager/ManagerHome";
import Placeholder from "@/features/manager/Placeholder";

/** Full-screen splash while the initial session check runs. */
function Splash() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-enamel">
      <div className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-green-deep" />
        <span className="font-head text-xl font-bold text-green-deep">
          Kaarigar
        </span>
      </div>
    </div>
  );
}

/** Guard: only lets the given roles through; otherwise redirects to the right place. */
function RequireRole({
  roles,
  children,
}: {
  roles: string[];
  children: ReactNode;
}) {
  const profile = useSessionStore((s) => s.profile);
  const loading = useSessionStore((s) => s.loading);

  if (loading) return <Splash />;
  if (!profile) {
    // Not signed in → the login screen for this area.
    return (
      <Navigate
        to={roles.includes("supervisor") ? "/manager/login" : "/login"}
        replace
      />
    );
  }
  if (!roles.includes(profile.role)) {
    return <Navigate to={homeForRole(profile.role)} replace />;
  }
  return <>{children}</>;
}

/** Guard: public screens redirect a signed-in user to their home. */
function PublicOnly({ children }: { children: ReactNode }) {
  const profile = useSessionStore((s) => s.profile);
  const loading = useSessionStore((s) => s.loading);

  if (loading) return <Splash />;
  if (profile) return <Navigate to={homeForRole(profile.role)} replace />;
  return <>{children}</>;
}

function RootRedirect() {
  const profile = useSessionStore((s) => s.profile);
  const loading = useSessionStore((s) => s.loading);

  if (loading) return <Splash />;
  if (profile) return <Navigate to={homeForRole(profile.role)} replace />;
  return <Navigate to="/login" replace />;
}

export default function Router() {
  const loadProfile = useSessionStore((s) => s.loadProfile);
  const location = useLocation();

  // On app start: if a Supabase session exists → loadProfile() (redirects happen in guards).
  useEffect(() => {
    void loadProfile();
  }, [loadProfile]);

  // Reset the i18n language choice when the user is looking at a login screen? No —
  // the pill choice persists; after login the profile language applies (see session store).

  // Document title stays constant.

  void location.pathname; // guards re-evaluate on navigation automatically

  return (
    <>
      <Routes>
        {/* Public */}
        <Route
          path="/login"
          element={
            <PublicOnly>
              <PhoneLogin />
            </PublicOnly>
          }
        />
        <Route
          path="/manager/login"
          element={
            <PublicOnly>
              <WebLogin />
            </PublicOnly>
          }
        />

        {/* Phone app */}
        <Route
          path="/tech"
          element={
            <RequireRole roles={["technician", "expert", "supervisor"]}>
              <TechHome />
            </RequireRole>
          }
        />

        {/* Web dashboard */}
        <Route
          path="/manager"
          element={
            <RequireRole roles={["supervisor"]}>
              <ManagerLayout />
            </RequireRole>
          }
        >
          <Route index element={<ManagerHome />} />
          <Route
            path="escalations"
            element={<Placeholder phase="4" title="Escalations" />}
          />
          <Route
            path="knowledge"
            element={<Placeholder phase="2" title="Knowledge base" />}
          />
          <Route
            path="analytics"
            element={<Placeholder phase="5" title="Analytics" />}
          />
          <Route path="team" element={<Placeholder phase="6" title="Team" />} />
          <Route
            path="setup/machines"
            element={<Placeholder phase="2" title="Setup › Machines" />}
          />
          <Route
            path="setup/documents"
            element={<Placeholder phase="1" title="Setup › Documents" />}
          />
          <Route
            path="setup/logs"
            element={<Placeholder phase="1" title="Setup › Breakdown logs" />}
          />
          <Route
            path="setup/people"
            element={<Placeholder phase="6" title="Setup › People" />}
          />
        </Route>

        {/* Catch-all */}
        <Route path="*" element={<RootRedirect />} />
      </Routes>
      <ToastViewport />
    </>
  );
}
