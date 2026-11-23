import { useDialogFocus } from '@/hooks/useDialogFocus'
import { useState, useRef, useEffect } from 'react'
import {
  Plus, Paperclip, Camera, FolderPlus, Sparkles, Globe,
  Wand2, Plug, Puzzle, Telescope, ChevronRight, Check, Loader2, Trash2, Lock, Slack as SlackIcon,
} from 'lucide-react'
import type { SimpleIcon } from 'simple-icons'
import {
  siAtlassian, siBitbucket, siCloudflare, siConfluence, siDocker, siFigma,
  siGithub, siGitlab, siGmail, siGoogledrive, siJira, siKubernetes,
  siLinear, siMongodb, siNotion, siPostgresql, siRedis,
  siSentry, siShopify, siSqlite, siStripe, siSupabase, siYoutube,
} from 'simple-icons'
import type { Project } from '@/types'
import { useMcpStatus } from '@/hooks/useMcpStatus'
import { useAuth } from '@/hooks/useAuth'
import { useSkills } from '@/hooks/useSkills'
import { SkillModal } from './SkillModal'
import { cn } from '@/lib/utils'

/**
 * chat/image are local UI states; agent routes through the real Dabba agent
 * loop (POST /v1/agent — web search, MCP connectors/plugins, research all
 * share this, only label/effort/hint differ); skill applies a saved
 * instruction as a system-prompt override for one message.
 */
export type ActiveMode =
  | { kind: 'chat' }
  | { kind: 'image' }
  | { kind: 'skill'; skillId: string; name: string }
  | { kind: 'agent'; label: string; effort?: string; hint?: string; allowedTools?: string[] }

interface PlusMenuProps {
  disabled?: boolean
  mode: ActiveMode
  onModeChange: (mode: ActiveMode) => void
  onAttachFiles: () => void
  onScreenshot: () => void
  projects: Project[]
  currentProjectId?: string | null
  onAddToProject: (projectId: string) => void
}

const CONNECTOR_MENU_ICONS: Record<string, SimpleIcon> = {
  atlassian: siAtlassian,
  bitbucket: siBitbucket,
  cloudflare: siCloudflare,
  confluence: siConfluence,
  docker: siDocker,
  figma: siFigma,
  github: siGithub,
  gitlab: siGitlab,
  gmail: siGmail,
  'google drive': siGoogledrive,
  drive: siGoogledrive,
  jira: siJira,
  kubernetes: siKubernetes,
  linear: siLinear,
  mongodb: siMongodb,
  notion: siNotion,
  postgres: siPostgresql,
  postgresql: siPostgresql,
  redis: siRedis,
  sentry: siSentry,
  shopify: siShopify,
  sqlite: siSqlite,
  stripe: siStripe,
  supabase: siSupabase,
  youtube: siYoutube,
}

export function ConnectorMenuIcon({ name, status, compact = false }: {
  name: string
  status?: 'connected' | 'available' | 'stopped'
  compact?: boolean
}) {
  const normalizedName = name.trim().toLowerCase()
  const icon = CONNECTOR_MENU_ICONS[normalizedName]
  return (
    <span className={cn(
      'relative flex flex-shrink-0 items-center justify-center',
      compact ? 'h-4 w-4 bg-transparent' : 'h-7 w-7 rounded-lg border border-border/70 bg-white dark:border-border-dark'
    )}>
      {normalizedName === 'linkedin' ? (
        <span aria-label="LinkedIn logo" role="img" className="text-[14px] font-extrabold leading-none tracking-[-0.08em] text-[#0A66C2]">in</span>
      ) : normalizedName === 'slack' ? (
        <SlackIcon aria-label="Slack logo" role="img" className="h-4 w-4 text-[#611f69]" />
      ) : icon ? (
        <svg className="h-4 w-4" viewBox="0 0 24 24" aria-label={`${name} logo`} role="img">
          <path fill={`#${icon.hex}`} d={icon.path} />
        </svg>
      ) : (
        <Plug className="h-3.5 w-3.5 text-text-tertiary" />
      )}
      {status && <span className={cn(
        'absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full border-2 border-surface dark:border-surface-dark-secondary',
        status === 'connected' ? 'bg-green-500' : status === 'available' ? 'bg-amber-500' : 'bg-gray-400'
      )} />}
    </span>
  )
}

export function PlusMenu({
  disabled,
  mode,
  onModeChange,
  onAttachFiles,
  onScreenshot,
  projects,
  currentProjectId,
  onAddToProject,
}: PlusMenuProps) {
  const [open, setOpen] = useState(false)
  const [submenu, setSubmenu] = useState<'projects' | 'connectors' | 'plugins' | 'skills' | null>(null)
  const [skillModalOpen, setSkillModalOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Agent modes (web search, connectors, plugins, research) go through
  // POST /v1/agent and MCP status through /v1/mcp/*, both admin-only.
  const { isAdmin } = useAuth()
  const { servers: mcpServers, isLoading: mcpLoading } = useMcpStatus(isAdmin && open && (submenu === 'connectors' || submenu === 'plugins'))
  const { skills, createSkill, deleteSkill } = useSkills()

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setSubmenu(null)
      }
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  const close = () => { setOpen(false); setSubmenu(null) }
  const menuRef = useDialogFocus(open, close)

  const setAgentMode = (label: string, effort?: string, hint?: string, allowedTools?: string[]) => {
    onModeChange(mode.kind === 'agent' && mode.label === label ? { kind: 'chat' } : { kind: 'agent', label, effort, hint, allowedTools })
    close()
  }


  const connectorAvailable = (server: typeof mcpServers[number]) =>
    server.connected || (!!server.processRunning && server.tools.length > 0)
  const allTools = mcpServers.flatMap(s => s.tools.map(t => ({
    server: s.name,
    tool: t,
    connected: connectorAvailable(s),
  })))

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        disabled={disabled}
        className="flex-shrink-0 p-3 pb-3.5 text-text-tertiary hover:text-text-primary dark:text-text-dark-tertiary dark:hover:text-text-dark-primary disabled:opacity-40 transition-colors rounded-l-2xl hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label="Add photos, files, and more"
        title="Add photos, files, and more"
      >
        <Plus className="w-5 h-5" />
      </button>

      {open && (
        <div ref={menuRef} role="dialog" aria-label="Add photos, files, and more" tabIndex={-1} className="absolute left-0 bottom-full mb-2 w-64 rounded-xl bg-surface dark:bg-surface-dark-secondary border border-border dark:border-border-dark shadow-lg z-40 py-1 animate-fade-in">
          <MenuItem icon={<Paperclip className="w-4 h-4" />} label="Add photos & files"
            onClick={() => { onAttachFiles(); close() }} />
          <MenuItem icon={<Camera className="w-4 h-4" />} label="Take screenshot"
            onClick={() => { onScreenshot(); close() }} />

          <Submenu label="Add to project" icon={<FolderPlus className="w-4 h-4" />}
            open={submenu === 'projects'} onToggle={() => setSubmenu(s => s === 'projects' ? null : 'projects')}>
            {projects.length === 0 ? (
              <EmptyHint>No projects yet. Create one from the sidebar.</EmptyHint>
            ) : (
              projects.map(p => (
                <SubItem key={p.id} onClick={() => { onAddToProject(p.id); close() }}
                  active={currentProjectId === p.id}>
                  <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: p.color }} />
                  <span className="truncate">{p.name}</span>
                </SubItem>
              ))
            )}
          </Submenu>

          <div className="my-1 border-t border-border dark:border-border-dark" />

          <MenuItem icon={<Wand2 className="w-4 h-4" />} label="Create an image" active={mode.kind === 'image'}
            onClick={() => { onModeChange(mode.kind === 'image' ? { kind: 'chat' } : { kind: 'image' }); close() }} />

          {isAdmin ? <>
          <MenuItem icon={<Globe className="w-4 h-4" />} label="Web search"
            active={mode.kind === 'agent' && mode.label === 'Web search'}
            onClick={() => setAgentMode('Web search')} />

          <Submenu label="Connectors" icon={<Plug className="w-4 h-4" />}
            open={submenu === 'connectors'} onToggle={() => setSubmenu(s => s === 'connectors' ? null : 'connectors')}>
            {mcpLoading ? (
              <LoadingHint />
            ) : mcpServers.length === 0 ? (
              <EmptyHint>No MCP connectors configured on the server.</EmptyHint>
            ) : (
              mcpServers.map(s => {
                const available = connectorAvailable(s)
                return <SubItem key={s.name}
                  onClick={() => available && setAgentMode(
                    `Connector: ${s.name}`, undefined, undefined,
                    s.tools.map(tool => `mcp__${s.name}__${tool}`),
                  )}
                  disabled={!available}
                  active={mode.kind === 'agent' && mode.label === `Connector: ${s.name}`}
                >
                  <ConnectorMenuIcon name={s.name} status={s.connected ? 'connected' : available ? 'available' : 'stopped'} />
                  <span className="truncate">{s.name}</span>
                  <span className="text-[9px] text-text-tertiary ml-auto flex-shrink-0">{s.tools.length} tools</span>
                </SubItem>
              })
            )}
          </Submenu>

          <Submenu label="Plugins" icon={<Puzzle className="w-4 h-4" />}
            open={submenu === 'plugins'} onToggle={() => setSubmenu(s => s === 'plugins' ? null : 'plugins')}>
            {mcpLoading ? (
              <LoadingHint />
            ) : allTools.length === 0 ? (
              <EmptyHint>No tools available — connect an MCP server first.</EmptyHint>
            ) : (
              allTools.map(({ server, tool, connected }) => (
                <SubItem key={`${server}.${tool}`}
                  onClick={() => connected && setAgentMode(
                    `Plugin: ${tool}`, undefined, undefined,
                    [`mcp__${server}__${tool}`],
                  )}
                  disabled={!connected}
                  active={mode.kind === 'agent' && mode.label === `Plugin: ${tool}`}
                >
                  <span className="truncate font-mono text-[11px]">{tool}</span>
                  <span className="text-[9px] text-text-tertiary ml-auto flex-shrink-0">{server}</span>
                </SubItem>
              ))
            )}
          </Submenu>

          <MenuItem icon={<Telescope className="w-4 h-4" />} label="Research"
            active={mode.kind === 'agent' && mode.label === 'Research'}
            onClick={() => setAgentMode(
              'Research', 'max',
              'Do thorough, multi-step research: search the web, follow up on ambiguous or conflicting results, ' +
              'and cite where each fact came from before giving a final answer.'
            )} />

          </> : <>
            {/* Regular users: show what exists, but locked, instead of a mode that fails on send. */}
            <MenuItem icon={<Globe className="w-4 h-4" />} label="Web search" disabled />
            <MenuItem icon={<Plug className="w-4 h-4" />} label="Connectors" disabled />
            <MenuItem icon={<Puzzle className="w-4 h-4" />} label="Plugins" disabled />
            <MenuItem icon={<Telescope className="w-4 h-4" />} label="Research" disabled />
          </>}

          <Submenu label="Skills" icon={<Sparkles className="w-4 h-4" />}
            open={submenu === 'skills'} onToggle={() => setSubmenu(s => s === 'skills' ? null : 'skills')}>
            {skills.length === 0 ? (
              <EmptyHint>No skills yet.</EmptyHint>
            ) : (
              skills.map(sk => (
                <SubItem key={sk.id}
                  onClick={() => { onModeChange(mode.kind === 'skill' && mode.skillId === sk.id ? { kind: 'chat' } : { kind: 'skill', skillId: sk.id, name: sk.name }); close() }}
                  active={mode.kind === 'skill' && mode.skillId === sk.id}
                >
                  <span className="truncate">{sk.name}</span>
                  <button
                    onClick={(e) => { e.stopPropagation(); deleteSkill(sk.id) }}
                    className="ml-auto flex-shrink-0 p-0.5 rounded hover:bg-red-500/10 text-text-tertiary hover:text-red-500"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </SubItem>
              ))
            )}
            <button
              onClick={() => { setSkillModalOpen(true); close() }}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors text-xs text-accent"
            >
              <Plus className="w-3.5 h-3.5" /> New skill…
            </button>
          </Submenu>
        </div>
      )}

      <SkillModal
        isOpen={skillModalOpen}
        onClose={() => setSkillModalOpen(false)}
        onSubmit={(input) => createSkill(input)}
      />
    </div>
  )
}

function MenuItem({ icon, label, onClick, active, trailing, disabled }: {
  icon: React.ReactNode; label: string; onClick?: () => void; active?: boolean; trailing?: React.ReactNode
  /** Admin-only feature for a regular user: shown with a lock, not clickable. */
  disabled?: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={disabled ? 'Owner only' : undefined}
      aria-label={disabled ? `${label} (owner only)` : undefined}
      className={cn(
        'w-full flex items-center justify-between gap-2 px-3 py-2 text-left transition-colors',
        disabled ? 'opacity-50 cursor-not-allowed'
          : active ? 'bg-accent/10' : 'hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary'
      )}
    >
      <span className={cn('flex items-center gap-2.5 text-xs', active ? 'text-accent font-medium' : 'text-text-primary dark:text-text-dark-primary')}>
        {icon}
        {label}
      </span>
      {disabled ? <Lock className="w-3 h-3 text-text-tertiary" aria-hidden="true" />
        : active ? <Check className="w-3.5 h-3.5 text-accent" /> : trailing}
    </button>
  )
}

function Submenu({ label, icon, open, onToggle, children }: {
  label: string; icon: React.ReactNode; open: boolean; onToggle: () => void; children: React.ReactNode
}) {
  return (
    <div className="relative">
      <MenuItem icon={icon} label={label} onClick={onToggle} trailing={<ChevronRight className="w-3.5 h-3.5 text-text-tertiary" />} />
      {open && (
        <div className="absolute left-full top-0 ml-1 w-56 max-h-64 overflow-y-auto scrollbar-thin rounded-xl bg-surface dark:bg-surface-dark-secondary border border-border dark:border-border-dark shadow-lg py-1">
          {children}
        </div>
      )}
    </div>
  )
}

function SubItem({ onClick, active, disabled, children }: {
  onClick?: () => void; active?: boolean; disabled?: boolean; children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'w-full flex items-center gap-2 px-3 py-1.5 text-left transition-colors text-xs',
        disabled
          ? 'opacity-45 cursor-not-allowed'
          : active
            ? 'bg-accent/10 text-accent font-medium'
            : 'hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-primary dark:text-text-dark-primary'
      )}
    >
      {children}
      {active && <Check className="w-3.5 h-3.5 text-accent flex-shrink-0 ml-auto" />}
    </button>
  )
}

function EmptyHint({ children }: { children: React.ReactNode }) {
  return <p className="px-3 py-2 text-[11px] text-text-tertiary">{children}</p>
}

function LoadingHint() {
  return (
    <div className="flex items-center gap-2 px-3 py-2 text-xs text-text-tertiary">
      <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
    </div>
  )
}
