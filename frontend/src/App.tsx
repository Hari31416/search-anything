import * as React from 'react'
import { ThemeProvider } from '@/components/theme-provider'
import { Header } from '@/components/header'
import { SearchTab } from '@/components/search/SearchTab'
import { LibraryTab } from '@/components/library/LibraryTab'
import { ProfilesTab } from '@/components/profiles/ProfilesTab'
import { WorkspaceProvider, useWorkspace } from '@/lib/workspaces'
import { Button } from '@/components/ui/button'
import { installExclusivePlayback } from '@/lib/media-playback'

function WorkspaceApp() {
  const { workspace, loading, error, reload } = useWorkspace()
  React.useEffect(() => installExclusivePlayback(), [])
  const [activeTab, setActiveTab] = React.useState<
    'search' | 'library' | 'profiles'
  >('search')

  return (
    <>
      <div className="flex min-h-screen flex-col bg-background font-sans text-foreground">
        <Header activeTab={activeTab} onSelectTab={setActiveTab} />

        <main
          key={workspace?.id ?? 'loading'}
          className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:px-8"
        >
          {loading ? (
            <p className="py-16 text-center text-sm text-muted-foreground">
              Loading workspaces...
            </p>
          ) : error ? (
            <div className="space-y-3 py-16 text-center">
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
              <Button variant="outline" onClick={() => void reload()}>
                Retry
              </Button>
            </div>
          ) : workspace ? (
            <>
              {activeTab === 'search' && <SearchTab />}
              {activeTab === 'library' && <LibraryTab />}
              {activeTab === 'profiles' && <ProfilesTab />}
            </>
          ) : (
            <p>No workspace available.</p>
          )}
        </main>
      </div>
    </>
  )
}

export function App() {
  return (
    <ThemeProvider defaultTheme="system" storageKey="search-anything-theme">
      <WorkspaceProvider>
        <WorkspaceApp />
      </WorkspaceProvider>
    </ThemeProvider>
  )
}

export default App
