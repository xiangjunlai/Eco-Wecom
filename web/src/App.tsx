import { useEffect, useState } from "react";
import { useAppStore } from "./store";
import { OnboardingDialog } from "./components/OnboardingDialog";
import { HomeView } from "./components/HomeView";
import { WorkspaceView } from "./components/WorkspaceView";
import { Toaster } from "./components/ui/toaster";

function App() {
  const { config, loadConfig } = useAppStore();
  const [showOnboarding, setShowOnboarding] = useState(false);

  useEffect(() => {
    loadConfig().then(() => {
      const { config } = useAppStore.getState();
      if (!config || !config.deepseek_api_key) {
        setShowOnboarding(true);
      }
    });
  }, []);

  const { activeWorkspace } = useAppStore();

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50">
      {!config && showOnboarding ? (
        <OnboardingDialog open={true} onOpenChange={setShowOnboarding} />
      ) : null}
      {activeWorkspace ? <WorkspaceView /> : <HomeView />}
      <Toaster />
    </div>
  );
}

export default App;