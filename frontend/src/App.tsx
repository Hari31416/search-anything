import * as React from 'react'
import { ThemeProvider } from '@/components/theme-provider'
import { Header } from '@/components/header'
import { SearchTab } from '@/components/search/SearchTab'
import { LibraryTab } from '@/components/library/LibraryTab'
import { ProfilesTab } from '@/components/profiles/ProfilesTab'

export function App() {
  const [activeTab, setActiveTab] = React.useState<
    'search' | 'library' | 'profiles'
  >('search')

  return (
    <ThemeProvider defaultTheme="system" storageKey="search-anything-theme">
      <div className="flex min-h-screen flex-col bg-background font-sans text-foreground">
        <Header activeTab={activeTab} onSelectTab={setActiveTab} />

        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:px-8">
          {activeTab === 'search' && <SearchTab />}
          {activeTab === 'library' && <LibraryTab />}
          {activeTab === 'profiles' && <ProfilesTab />}
        </main>

        <footer className="border-t border-border/60 py-4 text-center text-xs text-muted-foreground">
          <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-2 px-4 sm:flex-row">
            <div>
              Search Anything &bull; Local multimodal retrieval with
              EmbeddingGemma, Whisper &amp; pgvector
            </div>
            <div className="font-mono text-[11px]">
              API: 127.0.0.1:8000 &bull; Single-owner inference
            </div>
          </div>
        </footer>
      </div>
    </ThemeProvider>
  )
}

export default App
