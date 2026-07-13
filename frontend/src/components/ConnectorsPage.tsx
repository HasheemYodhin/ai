import { useMemo, useState, type ComponentType } from 'react'
import {
  Boxes, Bug, ChevronRight, Cloud, Database, FileText, Github, HardDrive, Loader2,
  MessageCircle, PenTool, Plug, Plus, RefreshCw, Search, Slack, Trash2,
  Triangle, Workflow, Wrench,
} from 'lucide-react'
import type { SimpleIcon } from 'simple-icons'
import {
  siAirtable, siAtlassian, siBitbucket, siCloudflare, siConfluence, siDiscord,
  siDocker, siDropbox, siFigma, siGithub, siGitlab, siGmail, siGooglecalendar,
  siGoogleanalytics, siGooglecloud, siGoogledocs, siGoogledrive, siGooglemaps,
  siGooglemeet, siGooglesheets, siGoogleslides, siJira, siKubernetes, siLinear, siMongodb, siNetlify,
  siNotion, siPostgresql, siRedis, siSentry, siShopify, siSqlite,
  siStripe, siSupabase, siVercel, siYoutube, siZapier,
} from 'simple-icons'
import { useMcpStatus } from '@/hooks/useMcpStatus'
import { ConnectorModal, type ConnectorPreset } from './ConnectorModal'
import { apiClient } from '@/api/client'
import { cn } from '@/lib/utils'

type ConnectorCategory = 'Productivity' | 'Microsoft' | 'Google' | 'Developer' | 'Data' | 'Cloud' | 'Commerce'
type CustomBrand = 'linkedin' | 'microsoft' | 'aws' | 'azure'

interface SuggestedConnector extends ConnectorPreset {
  id: string
  description: string
  category: ConnectorCategory
  icon: ComponentType<{ className?: string }>
  brand?: SimpleIcon
  brandColor?: string
  customBrand?: CustomBrand
  brandLabel?: string
  iconClass: string
  tileClass: string
}

function ConnectorIcon({ connector }: { connector: SuggestedConnector }) {
  if (connector.customBrand === 'linkedin') {
    return <span className="text-[17px] font-extrabold leading-none tracking-[-0.08em] text-[#0A66C2]">in</span>
  }
  if (connector.customBrand === 'microsoft') {
    if (connector.brandLabel) return <span className="text-base font-bold text-[#2563eb]">{connector.brandLabel}</span>
    return (
      <span className="grid h-5 w-5 grid-cols-2 gap-0.5">
        <span className="bg-[#f25022]" /><span className="bg-[#7fba00]" />
        <span className="bg-[#00a4ef]" /><span className="bg-[#ffb900]" />
      </span>
    )
  }
  if (connector.customBrand === 'aws') {
    return <span className="relative text-[13px] font-bold tracking-tight text-[#232f3e] dark:text-white">aws<span className="absolute -bottom-1 left-1 h-0.5 w-5 -rotate-6 rounded-full bg-[#ff9900]" /></span>
  }
  if (connector.customBrand === 'azure') {
    return <span className="text-base font-bold tracking-[-0.1em] text-[#0078d4]">AZ</span>
  }
  if (connector.brand) {
    return (
      <svg className="h-5 w-5" viewBox="0 0 24 24" role="img" aria-label={`${connector.name} logo`} style={{ color: connector.brandColor ?? `#${connector.brand.hex}` }}>
        <path fill="currentColor" d={connector.brand.path} />
      </svg>
    )
  }
  const Icon = connector.icon
  return <Icon className={cn('h-5 w-5', connector.iconClass)} />
}

const SUGGESTED_CONNECTORS: SuggestedConnector[] = [
  {
    id: 'github', name: 'GitHub', category: 'Developer', icon: Github, brand: siGithub, brandColor: '#ffffff',
    description: 'Work with repositories, issues, pull requests, and code.',
    command: 'npx', args: '-y @modelcontextprotocol/server-github',
    env: 'GITHUB_PERSONAL_ACCESS_TOKEN=',
    note: 'Create a GitHub personal access token and paste it after the equals sign.',
    iconClass: 'text-white', tileClass: 'bg-[#24292f]',
  },
  {
    id: 'notion', name: 'Notion', category: 'Productivity', icon: FileText, brand: siNotion, brandColor: '#ffffff',
    description: 'Search pages, read knowledge bases, and update documents.',
    command: 'npx', args: '-y @notionhq/notion-mcp-server',
    env: 'OPENAPI_MCP_HEADERS={"Authorization":"Bearer YOUR_NOTION_TOKEN","Notion-Version":"2022-06-28"}',
    note: 'Replace YOUR_NOTION_TOKEN and share the required pages with your Notion integration.',
    iconClass: 'text-white', tileClass: 'bg-black',
  },
  {
    id: 'drive', name: 'Google Drive', category: 'Google', icon: Triangle, brand: siGoogledrive,
    description: 'Find and read files stored across Google Drive.',
    command: 'npx', args: '-y @modelcontextprotocol/server-gdrive',
    note: 'Google OAuth credentials are required by the Drive MCP server.',
    iconClass: 'text-[#0F9D58]', tileClass: 'bg-[#eaf7ef] dark:bg-[#173c29]',
  },
  {
    id: 'slack', name: 'Slack', category: 'Productivity', icon: Slack,
    description: 'Search channels, read threads, and draft team updates.',
    command: 'npx', args: '-y @modelcontextprotocol/server-slack',
    env: 'SLACK_BOT_TOKEN=\nSLACK_TEAM_ID=',
    note: 'Add a Slack bot token and your workspace team ID.',
    iconClass: 'text-[#36C5F0]', tileClass: 'bg-[#f5eef6] dark:bg-[#37213b]',
  },
  {
    id: 'linear', name: 'Linear', category: 'Productivity', icon: Workflow, brand: siLinear,
    description: 'Manage product issues, cycles, projects, and roadmaps.',
    command: 'npx', args: '-y mcp-remote https://mcp.linear.app/sse',
    note: 'A browser authorization window may open the first time this connector starts.',
    iconClass: 'text-[#5E6AD2]', tileClass: 'bg-[#eeefff] dark:bg-[#25294b]',
  },
  {
    id: 'figma', name: 'Figma', category: 'Productivity', icon: PenTool, brand: siFigma,
    description: 'Bring design context and component details into your chats.',
    command: 'npx', args: '-y mcp-remote http://127.0.0.1:3845/sse',
    note: 'Start Figma desktop and enable its local MCP server before connecting.',
    iconClass: 'text-[#F24E1E]', tileClass: 'bg-[#fff0eb] dark:bg-[#45271f]',
  },
  {
    id: 'filesystem', name: 'Files', category: 'Developer', icon: HardDrive,
    description: 'Read and organize files in folders that you explicitly allow.',
    command: 'npx', args: '-y @modelcontextprotocol/server-filesystem /path/to/allowed/folder',
    note: 'Replace the example path with the folder this connector may access.',
    iconClass: 'text-amber-600', tileClass: 'bg-amber-50 dark:bg-amber-950/50',
  },
  {
    id: 'sentry', name: 'Sentry', category: 'Developer', icon: Bug, brand: siSentry,
    description: 'Investigate application errors, traces, and production issues.',
    command: 'npx', args: '-y mcp-remote https://mcp.sentry.dev/mcp',
    note: 'You will be asked to authorize access to your Sentry organization.',
    iconClass: 'text-[#6C5FC7]', tileClass: 'bg-[#f0edff] dark:bg-[#2f294f]',
  },
  {
    id: 'cloudflare', name: 'Cloudflare', category: 'Cloud', icon: Cloud, brand: siCloudflare,
    description: 'Inspect and manage Workers, logs, and Cloudflare resources.',
    iconClass: 'text-[#F48120]', tileClass: 'bg-[#fff2e6] dark:bg-[#452c19]',
  },
  {
    id: 'postgres', name: 'PostgreSQL', category: 'Data', icon: Database, brand: siPostgresql,
    description: 'Explore schemas and query a PostgreSQL database safely.',
    command: 'npx', args: '-y @modelcontextprotocol/server-postgres postgresql://localhost/mydb',
    note: 'Replace the example connection string and use a read-only database account when possible.',
    iconClass: 'text-[#336791]', tileClass: 'bg-[#eaf2f8] dark:bg-[#1e3442]',
  },
  {
    id: 'sqlite', name: 'SQLite', category: 'Data', icon: Database, brand: siSqlite,
    description: 'Ask questions about a local SQLite database file.',
    command: 'uvx', args: 'mcp-server-sqlite --db-path /path/to/database.db',
    note: 'Replace the example path with your SQLite database file.',
    iconClass: 'text-[#0F80CC]', tileClass: 'bg-sky-50 dark:bg-sky-950/50',
  },
  {
    id: 'jira', name: 'Jira', category: 'Productivity', icon: Workflow, brand: siJira,
    description: 'Search issues, update tickets, and plan engineering work.',
    command: 'npx', args: '-y mcp-remote https://mcp.atlassian.com/v1/sse',
    note: 'A browser window will ask you to authorize your Atlassian workspace.',
    iconClass: 'text-[#0052CC]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'confluence', name: 'Confluence', category: 'Productivity', icon: FileText, brand: siConfluence,
    description: 'Search team documentation, spaces, and internal knowledge.',
    command: 'npx', args: '-y mcp-remote https://mcp.atlassian.com/v1/sse',
    note: 'A browser window will ask you to authorize your Atlassian workspace.',
    iconClass: 'text-[#172B4D]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'atlassian', name: 'Atlassian', category: 'Productivity', icon: Boxes, brand: siAtlassian,
    description: 'Connect Jira and Confluence through one workspace account.',
    command: 'npx', args: '-y mcp-remote https://mcp.atlassian.com/v1/sse',
    note: 'A browser window will ask you to authorize your Atlassian workspace.',
    iconClass: 'text-[#0052CC]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'discord', name: 'Discord', category: 'Productivity', icon: MessageCircle, brand: siDiscord,
    description: 'Bring community channels, messages, and support context into chat.',
    note: 'Enter the launch command and credentials from your Discord MCP provider.',
    iconClass: 'text-[#5865F2]', tileClass: 'bg-indigo-50 dark:bg-indigo-950/50',
  },
  {
    id: 'gmail', name: 'Gmail', category: 'Google', icon: MessageCircle, brand: siGmail,
    description: 'Find email context and prepare replies without leaving Dabba.',
    note: 'Enter the launch command from your Gmail MCP provider and complete Google OAuth.',
    iconClass: 'text-[#EA4335]', tileClass: 'bg-red-50 dark:bg-red-950/40',
  },
  {
    id: 'calendar', name: 'Google Calendar', category: 'Google', icon: FileText, brand: siGooglecalendar,
    description: 'Check availability, inspect events, and coordinate schedules.',
    note: 'Enter the launch command from your Calendar MCP provider and complete Google OAuth.',
    iconClass: 'text-[#4285F4]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'dropbox', name: 'Dropbox', category: 'Productivity', icon: HardDrive, brand: siDropbox,
    description: 'Search and read shared files from your Dropbox workspace.',
    note: 'Enter the command and access token supplied by your Dropbox MCP provider.',
    iconClass: 'text-[#0061FF]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'airtable', name: 'Airtable', category: 'Productivity', icon: Boxes, brand: siAirtable,
    description: 'Query bases, track records, and automate lightweight workflows.',
    note: 'Enter the command and personal access token supplied by your Airtable MCP provider.',
    iconClass: 'text-[#18BFFF]', tileClass: 'bg-sky-50 dark:bg-sky-950/50',
  },
  {
    id: 'zapier', name: 'Zapier', category: 'Productivity', icon: Workflow, brand: siZapier,
    description: 'Trigger actions across thousands of apps and automated workflows.',
    note: 'Paste the MCP endpoint or launch command generated by your Zapier account.',
    iconClass: 'text-[#FF4F00]', tileClass: 'bg-orange-50 dark:bg-orange-950/40',
  },
  {
    id: 'gitlab', name: 'GitLab', category: 'Developer', icon: Github, brand: siGitlab,
    description: 'Work with projects, merge requests, pipelines, and issues.',
    note: 'Enter the command and access token supplied by your GitLab MCP provider.',
    iconClass: 'text-[#FC6D26]', tileClass: 'bg-orange-50 dark:bg-orange-950/40',
  },
  {
    id: 'bitbucket', name: 'Bitbucket', category: 'Developer', icon: Github, brand: siBitbucket,
    description: 'Access repositories, pull requests, commits, and pipelines.',
    note: 'Enter the command and app password supplied by your Bitbucket MCP provider.',
    iconClass: 'text-[#0052CC]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'docker', name: 'Docker', category: 'Developer', icon: Boxes, brand: siDocker,
    description: 'Inspect containers, images, logs, and local development services.',
    note: 'Enter your Docker MCP server command. Review its permissions before connecting.',
    iconClass: 'text-[#2496ED]', tileClass: 'bg-sky-50 dark:bg-sky-950/50',
  },
  {
    id: 'kubernetes', name: 'Kubernetes', category: 'Cloud', icon: Cloud, brand: siKubernetes,
    description: 'Explore clusters, workloads, events, and deployment health.',
    note: 'Enter your Kubernetes MCP command and use a least-privilege kubeconfig.',
    iconClass: 'text-[#326CE5]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'vercel', name: 'Vercel', category: 'Cloud', icon: Cloud, brand: siVercel,
    description: 'Inspect projects, deployments, domains, and runtime logs.',
    note: 'Enter the MCP command or endpoint supplied by your Vercel workspace.',
    iconClass: 'text-black', tileClass: 'bg-gray-100 dark:bg-white',
  },
  {
    id: 'netlify', name: 'Netlify', category: 'Cloud', icon: Cloud, brand: siNetlify,
    description: 'Work with sites, deploy previews, functions, and build activity.',
    note: 'Enter the MCP command and token supplied by your Netlify workspace.',
    iconClass: 'text-[#00C7B7]', tileClass: 'bg-teal-50 dark:bg-teal-950/50',
  },
  {
    id: 'supabase', name: 'Supabase', category: 'Data', icon: Database, brand: siSupabase,
    description: 'Explore projects, schemas, tables, edge functions, and logs.',
    command: 'npx', args: '-y mcp-remote https://mcp.supabase.com/mcp',
    note: 'A browser window may ask you to authorize your Supabase organization.',
    iconClass: 'text-[#3FCF8E]', tileClass: 'bg-emerald-50 dark:bg-emerald-950/50',
  },
  {
    id: 'mongodb', name: 'MongoDB', category: 'Data', icon: Database, brand: siMongodb,
    description: 'Inspect collections, query documents, and understand database structure.',
    note: 'Enter your MongoDB MCP command and prefer a read-only database user.',
    iconClass: 'text-[#47A248]', tileClass: 'bg-green-50 dark:bg-green-950/50',
  },
  {
    id: 'redis', name: 'Redis', category: 'Data', icon: Database, brand: siRedis,
    description: 'Inspect keys, cache behavior, streams, and application state.',
    note: 'Enter your Redis MCP command and use restricted credentials where possible.',
    iconClass: 'text-[#FF4438]', tileClass: 'bg-red-50 dark:bg-red-950/40',
  },
  {
    id: 'stripe', name: 'Stripe', category: 'Commerce', icon: Boxes, brand: siStripe,
    description: 'Investigate customers, payments, subscriptions, and invoices.',
    note: 'Enter the Stripe MCP command and a restricted API key.',
    iconClass: 'text-[#635BFF]', tileClass: 'bg-indigo-50 dark:bg-indigo-950/50',
  },
  {
    id: 'shopify', name: 'Shopify', category: 'Commerce', icon: Boxes, brand: siShopify,
    description: 'Work with products, orders, customers, and store operations.',
    note: 'Enter the Shopify MCP command and credentials for your store.',
    iconClass: 'text-[#7AB55C]', tileClass: 'bg-green-50 dark:bg-green-950/50',
  },
  {
    id: 'linkedin', name: 'LinkedIn', category: 'Productivity', icon: MessageCircle, customBrand: 'linkedin',
    description: 'Research professional profiles, companies, and industry context.',
    note: 'Enter the command and approved credentials from your LinkedIn MCP provider.',
    iconClass: 'text-[#0A66C2]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'microsoft365', name: 'Microsoft 365', category: 'Microsoft', icon: Boxes, customBrand: 'microsoft',
    description: 'Connect work across Microsoft documents, mail, meetings, and files.',
    note: 'Enter your Microsoft 365 MCP command and complete Microsoft identity authorization.',
    iconClass: 'text-blue-600', tileClass: 'bg-gray-50 dark:bg-gray-900',
  },
  {
    id: 'teams', name: 'Microsoft Teams', category: 'Microsoft', icon: MessageCircle, customBrand: 'microsoft', brandLabel: 'T',
    description: 'Search chats, channels, meetings, and team conversations.',
    note: 'Enter your Teams MCP command and complete Microsoft identity authorization.',
    iconClass: 'text-[#6264A7]', tileClass: 'bg-indigo-50 dark:bg-indigo-950/50',
  },
  {
    id: 'outlook', name: 'Microsoft Outlook', category: 'Microsoft', icon: MessageCircle, customBrand: 'microsoft', brandLabel: 'O',
    description: 'Find mail, draft replies, and work with calendar events.',
    note: 'Enter your Outlook MCP command and complete Microsoft identity authorization.',
    iconClass: 'text-[#0078D4]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'onedrive', name: 'Microsoft OneDrive', category: 'Microsoft', icon: Cloud, customBrand: 'microsoft', brandLabel: '1D',
    description: 'Search, read, and organize personal or shared cloud files.',
    note: 'Enter your OneDrive MCP command and complete Microsoft identity authorization.',
    iconClass: 'text-[#0078D4]', tileClass: 'bg-sky-50 dark:bg-sky-950/50',
  },
  {
    id: 'sharepoint', name: 'Microsoft SharePoint', category: 'Microsoft', icon: FileText, customBrand: 'microsoft', brandLabel: 'S',
    description: 'Use organization sites, documents, lists, and knowledge bases.',
    note: 'Enter your SharePoint MCP command and complete Microsoft identity authorization.',
    iconClass: 'text-[#038387]', tileClass: 'bg-teal-50 dark:bg-teal-950/50',
  },
  {
    id: 'powerbi', name: 'Microsoft Power BI', category: 'Microsoft', icon: Database, customBrand: 'microsoft', brandLabel: 'BI',
    description: 'Explore dashboards, datasets, reports, and business metrics.',
    note: 'Enter your Power BI MCP command and workspace credentials.',
    iconClass: 'text-[#F2C811]', tileClass: 'bg-yellow-50 dark:bg-yellow-950/40',
  },
  {
    id: 'dynamics', name: 'Microsoft Dynamics 365', category: 'Microsoft', icon: Workflow, customBrand: 'microsoft', brandLabel: 'D',
    description: 'Work with CRM records, customers, sales, and operations.',
    note: 'Enter your Dynamics 365 MCP command and tenant credentials.',
    iconClass: 'text-[#002050]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'azure-devops', name: 'Azure DevOps', category: 'Microsoft', icon: Workflow, customBrand: 'azure',
    description: 'Access repositories, boards, pipelines, artifacts, and test plans.',
    note: 'Enter your Azure DevOps MCP command and a least-privilege access token.',
    iconClass: 'text-[#0078D4]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'google-docs', name: 'Google Docs', category: 'Google', icon: FileText, brand: siGoogledocs,
    description: 'Read, summarize, and help edit collaborative documents.',
    note: 'Enter your Google Workspace MCP command and complete Google OAuth.',
    iconClass: 'text-[#4285F4]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'google-sheets', name: 'Google Sheets', category: 'Google', icon: Database, brand: siGooglesheets,
    description: 'Query spreadsheets, analyze tables, and update structured data.',
    note: 'Enter your Google Workspace MCP command and complete Google OAuth.',
    iconClass: 'text-[#34A853]', tileClass: 'bg-green-50 dark:bg-green-950/50',
  },
  {
    id: 'google-slides', name: 'Google Slides', category: 'Google', icon: FileText, brand: siGoogleslides,
    description: 'Read presentations and prepare structured slide content.',
    note: 'Enter your Google Workspace MCP command and complete Google OAuth.',
    iconClass: 'text-[#FBBC04]', tileClass: 'bg-yellow-50 dark:bg-yellow-950/40',
  },
  {
    id: 'google-meet', name: 'Google Meet', category: 'Google', icon: MessageCircle, brand: siGooglemeet,
    description: 'Work with meeting details, participants, and related context.',
    note: 'Enter your Google Workspace MCP command and complete Google OAuth.',
    iconClass: 'text-[#00897B]', tileClass: 'bg-emerald-50 dark:bg-emerald-950/50',
  },
  {
    id: 'google-maps', name: 'Google Maps', category: 'Google', icon: Cloud, brand: siGooglemaps,
    description: 'Search places, understand locations, and plan routes.',
    note: 'Enter your Google Maps MCP command and API credentials.',
    iconClass: 'text-[#4285F4]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'google-analytics', name: 'Google Analytics', category: 'Google', icon: Database, brand: siGoogleanalytics,
    description: 'Explore traffic, audiences, acquisition, and conversion metrics.',
    note: 'Enter your Analytics MCP command and complete Google authorization.',
    iconClass: 'text-[#E37400]', tileClass: 'bg-orange-50 dark:bg-orange-950/40',
  },
  {
    id: 'youtube', name: 'YouTube', category: 'Google', icon: MessageCircle, brand: siYoutube,
    description: 'Search videos, channels, captions, and publishing metadata.',
    note: 'Enter your YouTube MCP command and Google API credentials.',
    iconClass: 'text-[#FF0000]', tileClass: 'bg-red-50 dark:bg-red-950/40',
  },
  {
    id: 'aws', name: 'Amazon Web Services', category: 'Cloud', icon: Cloud, customBrand: 'aws',
    description: 'Connect cloud infrastructure, services, accounts, and operations.',
    note: 'Enter your AWS MCP command and use a least-privilege IAM profile.',
    iconClass: 'text-[#232F3E]', tileClass: 'bg-orange-50 dark:bg-orange-950/40',
  },
  {
    id: 'amazon-s3', name: 'Amazon S3', category: 'Cloud', icon: HardDrive, customBrand: 'aws',
    description: 'Search buckets, inspect objects, and manage cloud files.',
    note: 'Enter your AWS MCP command and grant access only to required buckets.',
    iconClass: 'text-[#569A31]', tileClass: 'bg-green-50 dark:bg-green-950/50',
  },
  {
    id: 'aws-lambda', name: 'AWS Lambda', category: 'Cloud', icon: Workflow, customBrand: 'aws',
    description: 'Inspect functions, configurations, invocations, and logs.',
    note: 'Enter your AWS MCP command and use a least-privilege IAM profile.',
    iconClass: 'text-[#FF9900]', tileClass: 'bg-orange-50 dark:bg-orange-950/40',
  },
  {
    id: 'cloudwatch', name: 'Amazon CloudWatch', category: 'Cloud', icon: Bug, customBrand: 'aws',
    description: 'Investigate logs, metrics, alarms, and service health.',
    note: 'Enter your AWS MCP command and use read-only observability permissions.',
    iconClass: 'text-[#759C3E]', tileClass: 'bg-purple-50 dark:bg-purple-950/40',
  },
  {
    id: 'bedrock', name: 'Amazon Bedrock', category: 'Cloud', icon: Boxes, customBrand: 'aws',
    description: 'Work with foundation models, knowledge bases, and AI agents.',
    note: 'Enter your AWS MCP command and configure Bedrock model access.',
    iconClass: 'text-[#8C4FFF]', tileClass: 'bg-purple-50 dark:bg-purple-950/40',
  },
  {
    id: 'azure', name: 'Microsoft Azure', category: 'Cloud', icon: Cloud, customBrand: 'azure',
    description: 'Inspect subscriptions, resources, deployments, and cloud operations.',
    note: 'Enter your Azure MCP command and complete tenant authorization.',
    iconClass: 'text-[#0078D4]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'azure-openai', name: 'Azure OpenAI', category: 'Cloud', icon: Boxes, customBrand: 'azure',
    description: 'Manage AI deployments, models, usage, and service configuration.',
    note: 'Enter your Azure MCP command and Azure OpenAI credentials.',
    iconClass: 'text-[#0078D4]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'azure-storage', name: 'Azure Blob Storage', category: 'Cloud', icon: HardDrive, customBrand: 'azure',
    description: 'Search containers, inspect blobs, and work with cloud files.',
    note: 'Enter your Azure MCP command and a restricted storage credential.',
    iconClass: 'text-[#0078D4]', tileClass: 'bg-sky-50 dark:bg-sky-950/50',
  },
  {
    id: 'google-cloud', name: 'Google Cloud', category: 'Cloud', icon: Cloud, brand: siGooglecloud,
    description: 'Connect projects, services, infrastructure, and cloud operations.',
    note: 'Enter your Google Cloud MCP command and use least-privilege credentials.',
    iconClass: 'text-[#4285F4]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'bigquery', name: 'Google BigQuery', category: 'Cloud', icon: Database, brand: siGooglecloud,
    description: 'Explore datasets and run analytical queries over cloud data.',
    note: 'Enter your Google Cloud MCP command and use a read-only service account.',
    iconClass: 'text-[#4285F4]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'gcs', name: 'Google Cloud Storage', category: 'Cloud', icon: HardDrive, brand: siGooglecloud,
    description: 'Search buckets, inspect objects, and manage cloud files.',
    note: 'Enter your Google Cloud MCP command and restrict bucket permissions.',
    iconClass: 'text-[#4285F4]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'vertex-ai', name: 'Google Vertex AI', category: 'Cloud', icon: Boxes, brand: siGooglecloud,
    description: 'Work with models, endpoints, pipelines, and AI platform resources.',
    note: 'Enter your Google Cloud MCP command and Vertex AI credentials.',
    iconClass: 'text-[#4285F4]', tileClass: 'bg-blue-50 dark:bg-blue-950/50',
  },
  {
    id: 'custom', name: 'Custom MCP', category: 'Developer', icon: Boxes,
    description: 'Connect any local or remote MCP-compatible service.',
    iconClass: 'text-accent', tileClass: 'bg-accent/10',
  },
]

interface ConnectorsPageProps {
  onOpenSkills?: () => void
}

const FEATURED_IDS = new Set(['github', 'notion', 'linkedin', 'microsoft365', 'drive', 'aws', 'azure', 'google-cloud'])

interface ConnectorSectionProps {
  title: string
  connectors: SuggestedConnector[]
  installed: Set<string>
  onConnect: (connector: ConnectorPreset) => void
}

function ConnectorSection({ title, connectors, installed, onConnect }: ConnectorSectionProps) {
  if (connectors.length === 0) return null

  return (
    <section>
      <div className="mb-2 flex items-center gap-0.5">
        <h2 className="text-xs font-semibold text-text-primary dark:text-text-dark-primary">{title}</h2>
        <ChevronRight className="h-3.5 w-3.5 text-text-tertiary" />
      </div>
      <div className="grid grid-cols-1 gap-x-8 gap-y-1 sm:grid-cols-2">
        {connectors.map(connector => {
          const isInstalled = installed.has(connector.name.toLowerCase())
          return (
            <button key={connector.id} onClick={() => !isInstalled && onConnect(connector)} disabled={isInstalled} className="group flex min-w-0 items-center gap-3 rounded-xl px-1 py-2 text-left transition-colors hover:bg-surface-secondary disabled:cursor-default disabled:opacity-60 dark:hover:bg-surface-dark-tertiary">
              <span className={cn('flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl border border-border/60 dark:border-border-dark', connector.tileClass)}><ConnectorIcon connector={connector} /></span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-semibold text-text-primary dark:text-text-dark-primary">{connector.name}</span>
                <span className="block truncate text-[11px] text-text-secondary dark:text-text-dark-secondary">{connector.description}</span>
              </span>
              <span className={cn('flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full transition-colors', isInstalled ? 'text-emerald-500' : 'text-text-tertiary group-hover:bg-surface-tertiary group-hover:text-accent dark:group-hover:bg-surface-dark-secondary')} title={isInstalled ? 'Installed' : `Connect ${connector.name}`}>
                {isInstalled ? <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> : <Plus className="h-4 w-4" />}
              </span>
            </button>
          )
        })}
      </div>
    </section>
  )
}

/** Real MCP connections plus a curated setup catalog. */
export function ConnectorsPage({ onOpenSkills }: ConnectorsPageProps) {
  const { servers, isLoading, error, reload } = useMcpStatus(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [preset, setPreset] = useState<ConnectorPreset | null>(null)
  const [deletingName, setDeletingName] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  const installed = useMemo(() => new Set(servers.map(server => server.name.toLowerCase())), [servers])
  const suggestions = useMemo(() => {
    const term = query.trim().toLowerCase()
    return SUGGESTED_CONNECTORS.filter(connector =>
      !term || `${connector.name} ${connector.description} ${connector.category}`.toLowerCase().includes(term)
    )
  }, [query])

  const openConnector = (nextPreset: ConnectorPreset | null = null) => {
    setPreset(nextPreset)
    setModalOpen(true)
  }

  const handleAdd = async (input: { name: string; command: string; args: string[]; env?: Record<string, string> }) => {
    await apiClient.addMcpServer(input)
    reload()
  }

  const handleDelete = async (name: string) => {
    if (!confirm(`Remove connector "${name}"? If it is connected, it stays live until the server restarts.`)) return
    setDeletingName(name)
    try {
      await apiClient.deleteMcpServer(name)
      reload()
    } catch (err) {
      alert((err as Error).message)
    } finally {
      setDeletingName(null)
    }
  }

  return (
    <div className="h-full overflow-y-auto scrollbar-thin bg-surface dark:bg-surface-dark">
      <div className="sticky top-0 z-20 border-b border-border/70 bg-surface/90 px-4 py-2.5 backdrop-blur dark:border-border-dark/70 dark:bg-surface-dark/90">
        <div className="mx-auto flex w-fit rounded-full bg-surface-secondary p-0.5 dark:bg-surface-dark-tertiary">
          <button className="rounded-full bg-surface px-5 py-1.5 text-xs font-semibold text-text-primary shadow-sm dark:bg-surface-dark-secondary dark:text-text-dark-primary">Connectors</button>
          <button onClick={onOpenSkills} className="rounded-full px-5 py-1.5 text-xs font-semibold text-text-secondary transition-colors hover:text-text-primary dark:text-text-dark-secondary dark:hover:text-text-dark-primary">Skills</button>
        </div>
      </div>

      <main className="mx-auto w-full max-w-4xl px-5 py-10 sm:px-8">
        <div className="mb-8 flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-text-primary dark:text-text-dark-primary">Connectors</h1>
            <p className="mt-1 text-sm text-text-secondary dark:text-text-dark-secondary">Work with Dabba across your favorite tools.</p>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative w-full sm:w-60">
              <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-tertiary" />
              <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search connectors" className="glass-input w-full rounded-full py-2 pl-9 pr-3 text-xs outline-none transition-colors focus:border-accent/40" />
            </div>
            <button onClick={() => openConnector()} className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full border border-border text-text-secondary transition-colors hover:border-accent/40 hover:text-accent dark:border-border-dark" title="Add custom connector"><Plus className="h-4 w-4" /></button>
          </div>
        </div>

        <section className="mb-9">
          <div className="mb-3 flex items-center gap-2">
            <h2 className="text-xs font-semibold text-text-primary dark:text-text-dark-primary">Installed</h2>
            <span className="text-[10px] text-text-tertiary">{servers.length}</span>
            <button onClick={reload} className="ml-auto rounded-md p-1 text-text-tertiary transition-colors hover:text-text-primary dark:hover:text-text-dark-primary" title="Refresh"><RefreshCw className="h-3.5 w-3.5" /></button>
          </div>
          {isLoading ? (
            <div className="flex h-11 items-center gap-2 text-xs text-text-tertiary"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading...</div>
          ) : error ? (
            <div className="rounded-xl bg-red-500/5 px-3 py-2 text-xs text-red-500">{error}</div>
          ) : servers.length === 0 ? (
            <button onClick={() => openConnector(SUGGESTED_CONNECTORS[0])} className="flex items-center gap-2 text-xs text-text-tertiary transition-colors hover:text-accent"><Plus className="h-4 w-4" /> Add your first connector</button>
          ) : (
            <div className="flex flex-wrap gap-2">
              {servers.map(server => {
                const catalogConnector = SUGGESTED_CONNECTORS.find(connector => connector.name.toLowerCase() === server.name.toLowerCase())
                return (
                  <div key={server.name} className="group relative" title={`${server.name} - ${server.connected ? `${server.tools?.length ?? 0} tools` : 'disconnected'}`}>
                    <span className={cn('relative flex h-10 w-10 items-center justify-center rounded-xl border border-border/70 dark:border-border-dark', catalogConnector?.tileClass ?? 'bg-surface-secondary dark:bg-surface-dark-tertiary')}>
                      {catalogConnector ? <ConnectorIcon connector={catalogConnector} /> : <Plug className="h-4 w-4 text-text-tertiary" />}
                      <span className={cn('absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-surface dark:border-surface-dark', server.connected ? 'bg-emerald-500' : 'bg-gray-400')} />
                    </span>
                    <button onClick={() => handleDelete(server.name)} disabled={deletingName === server.name} className="absolute -right-1.5 -top-1.5 hidden h-5 w-5 items-center justify-center rounded-full bg-surface text-red-500 shadow ring-1 ring-border group-hover:flex dark:bg-surface-dark-secondary dark:ring-border-dark" title={`Remove ${server.name}`}>
                      {deletingName === server.name ? <Loader2 className="h-2.5 w-2.5 animate-spin" /> : <Trash2 className="h-2.5 w-2.5" />}
                    </button>
                  </div>
                )
              })}
            </div>
          )}
        </section>

        {query.trim() ? (
          <ConnectorSection title="Results" connectors={suggestions} installed={installed} onConnect={openConnector} />
        ) : (
          <div className="space-y-8">
            <ConnectorSection title="Featured" connectors={SUGGESTED_CONNECTORS.filter(connector => FEATURED_IDS.has(connector.id))} installed={installed} onConnect={openConnector} />
            {(['Productivity', 'Microsoft', 'Google', 'Developer', 'Data', 'Cloud', 'Commerce'] as ConnectorCategory[]).map(group => (
              <ConnectorSection key={group} title={group} connectors={SUGGESTED_CONNECTORS.filter(connector => connector.category === group)} installed={installed} onConnect={openConnector} />
            ))}
          </div>
        )}
        {query.trim() && suggestions.length === 0 && <div className="py-12 text-center text-sm text-text-tertiary">No connectors match your search.</div>}
      </main>

      <ConnectorModal isOpen={modalOpen} preset={preset} onClose={() => setModalOpen(false)} onSubmit={handleAdd} />
    </div>
  )
}
