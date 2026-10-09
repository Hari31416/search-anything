import * as React from 'react'
import {
  Moon,
  Sun,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  RefreshCw,
  Search,
  Layers,
  SlidersHorizontal,
  Sparkles,
} from 'lucide-react'
import { useTheme } from '@/components/theme-provider'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
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
  const [checking, setChecking] = React.useState(false)

  const checkHealth = React.useCallback(async () => {
    setChecking(true)
    try {
      const data = await api.getHealth()
      setHealth(data)
      setHealthError(null)
    } catch (err) {
      setHealth(null)
      setHealthError(err instanceof Error ? err.message : 'Backend offline')
    } finally {
      setChecking(false)
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
            <div className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-tr from-primary to-violet-500 font-bold text-white shadow-md shadow-primary/20">
              <Sparkles className="size-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-base font-extrabold tracking-tight text-foreground">
                  Search Anything
                </span>
                <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
                  Multimodal
                </span>
              </div>
              <p className="hidden text-[11px] text-muted-foreground sm:block">
                Visual, auditory & textual vector search
              </p>
            </div>
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
          <div className="flex items-center gap-2">
            {health ? (
              <Badge
                variant="success"
                className="gap-1.5 border-emerald-500/25 bg-emerald-500/15 text-[11px] font-medium text-emerald-600 dark:text-emerald-400"
              >
                <CheckCircle2 className="size-3 text-emerald-500" />
                <span className="hidden md:inline">Storage & DB Ready</span>
                <span className="md:hidden">Ready</span>
              </Badge>
            ) : healthError ? (
              <Badge
                variant="destructive"
                className="gap-1.5 text-[11px] font-normal"
                title={healthError}
              >
                <XCircle className="size-3 text-destructive" />
                <span className="hidden md:inline">Services Offline</span>
                <span className="md:hidden">Offline</span>
              </Badge>
            ) : (
              <Badge
                variant="warning"
                className="gap-1.5 text-[11px] font-normal"
              >
                <AlertTriangle className="size-3 text-amber-500" />
                Connecting...
              </Badge>
            )}

            <Button
              variant="ghost"
              size="icon-xs"
              onClick={checkHealth}
              disabled={checking}
              aria-label="Refresh backend status"
              title="Refresh backend status"
              className="rounded-lg"
            >
              <RefreshCw
                className={`size-3 text-muted-foreground ${checking ? 'animate-spin' : ''}`}
              />
            </Button>
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
