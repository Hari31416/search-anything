import * as React from 'react'
import { Moon, Sun, Search, Layers, SlidersHorizontal } from 'lucide-react'
import { useTheme } from '@/components/theme-provider'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import type { ReadinessResponse } from '@/types/api'

interface HeaderProps {
  activeTab: 'search' | 'library' | 'profiles'
  onSelectTab: (tab: 'search' | 'library' | 'profiles') => void
}

export function Header({ activeTab, onSelectTab }: HeaderProps) {
  const { theme, setTheme } = useTheme()
  const [health, setHealth] = React.useState<ReadinessResponse | null>(null)
  const [healthError, setHealthError] = React.useState<string | null>(null)
  const checkHealth = React.useCallback(async () => {
    try {
      const data = await api.getHealth()
      setHealth(data)
      setHealthError(null)
    } catch (err) {
      setHealth(null)
      setHealthError(err instanceof Error ? err.message : 'Backend offline')
    }
  }, [])

  React.useEffect(() => {
    checkHealth()
    const interval = setInterval(checkHealth, 20000)
    return () => clearInterval(interval)
  }, [checkHealth])

  const toggleTheme = () => {
    setTheme(theme === 'dark' ? 'light' : 'dark')
  }

  return (
    <header className="sticky top-0 z-40 w-full border-b border-border/80 bg-background/80 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-xl bg-primary font-bold text-primary-foreground shadow-xs">
              <Search className="size-4.5" />
            </div>
            <span className="text-base font-extrabold tracking-tight text-foreground">
              Search Anything
            </span>
          </div>

          <nav
            className="hidden items-center gap-1 sm:flex"
            aria-label="Main Navigation"
          >
            <button
              type="button"
              onClick={() => onSelectTab('search')}
              className={`flex items-center gap-1.5 rounded-xl px-3.5 py-1.5 text-xs font-semibold transition-all ${
                activeTab === 'search'
                  ? 'bg-primary text-primary-foreground shadow-2xs'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
            >
              <Search className="size-3.5" />
              <span>Search</span>
            </button>
            <button
              type="button"
              onClick={() => onSelectTab('library')}
              className={`flex items-center gap-1.5 rounded-xl px-3.5 py-1.5 text-xs font-semibold transition-all ${
                activeTab === 'library'
                  ? 'bg-primary text-primary-foreground shadow-2xs'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
            >
              <Layers className="size-3.5" />
              <span>Library</span>
            </button>
            <button
              type="button"
              onClick={() => onSelectTab('profiles')}
              className={`flex items-center gap-1.5 rounded-xl px-3.5 py-1.5 text-xs font-semibold transition-all ${
                activeTab === 'profiles'
                  ? 'bg-primary text-primary-foreground shadow-2xs'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
            >
              <SlidersHorizontal className="size-3.5" />
              <span>Profiles</span>
            </button>
          </nav>
        </div>

        <div className="flex items-center gap-3">
          {/* Subtle minimal status indicator */}
          <div
            className="flex items-center"
            title={
              health
                ? 'Backend Ready'
                : healthError
                  ? `Offline: ${healthError}`
                  : 'Connecting...'
            }
          >
            <span
              className={`size-2 rounded-full ${
                health
                  ? 'bg-emerald-500'
                  : healthError
                    ? 'bg-destructive'
                    : 'animate-pulse bg-amber-500'
              }`}
            />
          </div>

          <div className="h-4 w-px bg-border/80" />

          <Button
            variant="ghost"
            size="icon-sm"
            onClick={toggleTheme}
            aria-label="Toggle color theme"
            title="Toggle theme"
            className="rounded-xl"
          >
            {theme === 'dark' ? (
              <Sun className="size-4 text-foreground" />
            ) : (
              <Moon className="size-4 text-foreground" />
            )}
          </Button>
        </div>
      </div>

      <div
        className="flex border-t border-border px-4 py-2 sm:hidden"
        aria-label="Mobile Navigation"
      >
        <div className="flex w-full justify-around gap-1">
          <button
            type="button"
            onClick={() => onSelectTab('search')}
            className={`flex flex-1 items-center justify-center gap-1 rounded-xl py-1.5 text-center text-xs font-semibold ${
              activeTab === 'search'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground'
            }`}
          >
            <Search className="size-3" />
            <span>Search</span>
          </button>
          <button
            type="button"
            onClick={() => onSelectTab('library')}
            className={`flex flex-1 items-center justify-center gap-1 rounded-xl py-1.5 text-center text-xs font-semibold ${
              activeTab === 'library'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground'
            }`}
          >
            <Layers className="size-3" />
            <span>Library</span>
          </button>
          <button
            type="button"
            onClick={() => onSelectTab('profiles')}
            className={`flex flex-1 items-center justify-center gap-1 rounded-xl py-1.5 text-center text-xs font-semibold ${
              activeTab === 'profiles'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground'
            }`}
          >
            <SlidersHorizontal className="size-3" />
            <span>Profiles</span>
          </button>
        </div>
      </div>
    </header>
  )
}
