import { Suspense, useEffect, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ToastViewport } from "@/components/ui/toast";
import { homeForRole, useSessionStore } from "@/stores/session";
import PhoneLogin from "@/features/auth/PhoneLogin";
import WebLogin from "@/features/auth/WebLogin";
import TechHome from "@/features/tech/TechHome";
import MachineScreen from "@/features/capture/MachineScreen";
import RecordScreen from "@/features/capture/RecordScreen";
import NoteScreen from "@/features/capture/NoteScreen";
import SentScreen from "@/features/capture/SentScreen";
import ManagerLayout from "@/features/manager/ManagerLayout";
import ReviewQueue from "@/features/manager/review/ReviewQueue";
import EscalationsPage from "@/features/manager/escalations/EscalationsPage";
import KnowledgePage from "@/features/manager/knowledge/KnowledgePage";
import AnalyticsPage from "@/features/manager/analytics/AnalyticsPage";
import MachinesPage from "@/features/manager/setup/MachinesPage";
import StickerSheet from "@/features/manager/setup/StickerSheet";
import DocumentsPage from "@/features/manager/setup/DocumentsPage";
import BreakdownLogsPage from "@/features/manager/setup/BreakdownLogsPage";
import PeoplePage from "@/features/manager/setup/PeoplePage";
import ScanScreen from "@/features/scan/ScanScreen";
import AskScreen from "@/features/assist/AskScreen";
import MyQuestions from "@/features/assist/MyQuestions";
import QuestionScreen from "@/features/assist/QuestionScreen";
import ExpertInbox from "@/features/assist/ExpertInbox";
import EscalationAnswerScreen from "@/features/assist/EscalationAnswerScreen";
import QrRedirect from "@/features/assist/QrRedirect";

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
  loginTo,
  children,
}: {
  roles: string[];
  /** Login screen for this area — /tech sends back to /login, /manager to /manager/login. */
  loginTo: string;
  children: ReactNode;
}) {
  const profile = useSessionStore((s) => s.profile);
  const loading = useSessionStore((s) => s.loading);

  if (loading) return <Splash />;
  if (!profile) {
    // Not signed in → the login screen for this area.
    return <Navigate to={loginTo} replace />;
  }
  if (!roles.includes(profile.role)) {
    return <Navigate to={homeForRole(profile.role)} replace />;
  }
  return <>{children}</>;
}

/** Guard: plant-admin-only manager routes (Meena, a non-admin supervisor, goes back to /manager). */
function RequireAdmin({ children }: { children: ReactNode }) {
  const profile = useSessionStore((s) => s.profile);
  const loading = useSessionStore((s) => s.loading);

  if (loading) return <Splash />;
  if (!profile?.is_admin) return <Navigate to="/manager" replace />;
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
      {/* Lazy locale chunks suspend on first render / language switch —
          the Splash keeps the current screen mounted instead of blanking. */}
      <Suspense fallback={<Splash />}>
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
            <RequireRole roles={["technician", "expert", "supervisor"]} loginTo="/login">
              <TechHome />
            </RequireRole>
          }
        />
        <Route
          path="/tech/machines/:code"
          element={
            <RequireRole roles={["technician", "expert", "supervisor"]} loginTo="/login">
              <MachineScreen />
            </RequireRole>
          }
        />
        <Route
          path="/tech/machines/:code/record"
          element={
            <RequireRole roles={["technician", "expert", "supervisor"]} loginTo="/login">
              <RecordScreen />
            </RequireRole>
          }
        />
        <Route
          path="/tech/machines/:code/ask"
          element={
            <RequireRole roles={["technician", "expert", "supervisor"]} loginTo="/login">
              <AskScreen />
            </RequireRole>
          }
        />
        <Route
          path="/tech/ask"
          element={
            <RequireRole roles={["technician", "expert", "supervisor"]} loginTo="/login">
              <AskScreen />
            </RequireRole>
          }
        />
        <Route
          path="/tech/scan"
          element={
            <RequireRole roles={["technician", "expert", "supervisor"]} loginTo="/login">
              <ScanScreen />
            </RequireRole>
          }
        />
        <Route
          path="/tech/questions"
          element={
            <RequireRole roles={["technician", "expert", "supervisor"]} loginTo="/login">
              <MyQuestions />
            </RequireRole>
          }
        />
        <Route
          path="/tech/questions/:id"
          element={
            <RequireRole roles={["technician", "expert", "supervisor"]} loginTo="/login">
              <QuestionScreen />
            </RequireRole>
          }
        />
        <Route
          path="/tech/inbox"
          element={
            <RequireRole roles={["expert", "supervisor"]} loginTo="/login">
              <ExpertInbox />
            </RequireRole>
          }
        />
        <Route
          path="/tech/inbox/:id"
          element={
            <RequireRole roles={["expert", "supervisor"]} loginTo="/login">
              <EscalationAnswerScreen />
            </RequireRole>
          }
        />
        <Route
          path="/m/:token"
          element={
            <RequireRole roles={["technician", "expert", "supervisor"]} loginTo="/login">
              <QrRedirect />
            </RequireRole>
          }
        />
        <Route
          path="/tech/records/:id"
          element={
            <RequireRole roles={["technician", "expert", "supervisor"]} loginTo="/login">
              <NoteScreen />
            </RequireRole>
          }
        />
        <Route
          path="/tech/records/:id/sent"
          element={
            <RequireRole roles={["technician", "expert", "supervisor"]} loginTo="/login">
              <SentScreen />
            </RequireRole>
          }
        />

        {/* Web dashboard */}
        <Route
          path="/manager"
          element={
            <RequireRole roles={["supervisor"]} loginTo="/manager/login">
              <ManagerLayout />
            </RequireRole>
          }
        >
          <Route index element={<ReviewQueue />} />
          <Route path="escalations" element={<EscalationsPage />} />
          <Route path="knowledge" element={<KnowledgePage />} />
          <Route path="analytics" element={<AnalyticsPage />} />
          <Route
            path="setup/machines"
            element={
              <RequireAdmin>
                <MachinesPage />
              </RequireAdmin>
            }
          />
          <Route
            path="setup/machines/stickers"
            element={
              <RequireAdmin>
                <StickerSheet />
              </RequireAdmin>
            }
          />
          <Route
            path="setup/documents"
            element={
              <RequireAdmin>
                <DocumentsPage />
              </RequireAdmin>
            }
          />
          <Route
            path="setup/logs"
            element={
              <RequireAdmin>
                <BreakdownLogsPage />
              </RequireAdmin>
            }
          />
          <Route
            path="setup/people"
            element={
              <RequireAdmin>
                <PeoplePage />
              </RequireAdmin>
            }
          />
        </Route>

        {/* Catch-all */}
        <Route path="*" element={<RootRedirect />} />
      </Routes>
      </Suspense>
      <ToastViewport />
    </>
  );
}
