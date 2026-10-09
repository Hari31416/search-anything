import * as React from 'react'
import {
  Moon,
  Sun,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  RefreshCw,
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
    <header className="sticky top-0 z-40 w-full border-b border-border bg-background/95 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2.5">
            <div className="flex size-9 items-center justify-center rounded-lg bg-primary font-bold text-primary-foreground shadow-xs">
              SA
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-base font-bold tracking-tight text-foreground">
                  Search Anything
                </span>
                <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
                  Local Multimodal
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                Documents, images, audio, and video
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
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                activeTab === 'search'
                  ? 'bg-secondary text-secondary-foreground shadow-2xs'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
            >
              Search
            </button>
            <button
              type="button"
              onClick={() => onSelectTab('library')}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                activeTab === 'library'
                  ? 'bg-secondary text-secondary-foreground shadow-2xs'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
            >
              Library
            </button>
            <button
              type="button"
              onClick={() => onSelectTab('profiles')}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                activeTab === 'profiles'
                  ? 'bg-secondary text-secondary-foreground shadow-2xs'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
            >
              Profiles
            </button>
          </nav>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            {health ? (
              <Badge
                variant="success"
                className="gap-1.5 text-[11px] font-normal"
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
            >
              <RefreshCw
                className={`size-3 text-muted-foreground ${checking ? 'animate-spin' : ''}`}
              />
            </Button>
          </div>

          <div className="h-4 w-px bg-border" />

          <Button
            variant="ghost"
            size="icon-sm"
            onClick={toggleTheme}
            aria-label="Toggle color theme"
            title="Toggle theme (Press 'd')"
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
        className="flex border-t border-border px-4 py-1.5 sm:hidden"
        aria-label="Mobile Navigation"
      >
        <div className="flex w-full justify-around">
          <button
            type="button"
            onClick={() => onSelectTab('search')}
            className={`flex-1 rounded-sm py-1 text-center text-xs font-medium ${
              activeTab === 'search'
                ? 'bg-secondary text-foreground'
                : 'text-muted-foreground'
            }`}
          >
            Search
          </button>
          <button
            type="button"
            onClick={() => onSelectTab('library')}
            className={`flex-1 rounded-sm py-1 text-center text-xs font-medium ${
              activeTab === 'library'
                ? 'bg-secondary text-foreground'
                : 'text-muted-foreground'
            }`}
          >
            Library
          </button>
          <button
            type="button"
            onClick={() => onSelectTab('profiles')}
            className={`flex-1 rounded-sm py-1 text-center text-xs font-medium ${
              activeTab === 'profiles'
                ? 'bg-secondary text-foreground'
                : 'text-muted-foreground'
            }`}
          >
            Profiles
          </button>
        </div>
      </div>
    </header>
  )
}
