/**
 * Copy for the public landing page (`/`). Edit text here; the layout lives in
 * components/LandingPage.tsx. Every number is taken from the codebase
 * (model picker, provider registry, connector catalogue). Nothing is invented,
 * so there are no user counts, ratings, prices or customer quotes.
 */

export type LandingLink = { label: string; href: string }

export interface LandingContent {
  nav: LandingLink[]
  hero: {
    proofTitle: string
    proofLink: LandingLink
    headline: string
    headlineMark: string
    subheadline: [string, string]
    badgeTitle: string
    badgeText: string
    badgeAside: string
    primaryCta: string
    secondaryCta: string
  }
  panel: {
    chips: { text: string; tone: 'orange' | 'blue' }[]
    stat: { label: string; value: string; caption: string }
    task: { title: string; schedule: string; status: string; result: string }
  }
  worksWith: string[]
  features: { title: string; text: string }[]
  capabilities: { title: string; text: string }[]
  models: { title: string; text: string; providers: { name: string; family: string }[]; connectorsTitle: string; connectorsText: string; connectors: string[] }
  security: { title: string; text: string }[]
  footerLinks: LandingLink[]
  steps: { title: string; text: string }[]
  stats: { value: string; label: string }[]
  quote: { text: string; source: string }
  plans: { name: string; tag: string; summary: string; points: string[]; cta: string; target: 'try' | 'signup'; featured?: boolean }[]
  faqs: { q: string; a: string }[]
  finalCta: { title: string; text: string }
}

export const LANDING: LandingContent = {
  nav: [
    { label: 'Product', href: '#features' },
    { label: 'Models', href: '#models' },
    { label: 'How it works', href: '#how-it-works' },
    { label: 'Security', href: '#security' },
    { label: 'FAQ', href: '#faq' },
  ],
  footerLinks: [
    { label: 'Product', href: '#features' },
    { label: 'Models and connectors', href: '#models' },
    { label: 'How it works', href: '#how-it-works' },
    { label: 'Security', href: '#security' },
    { label: 'Plans', href: '#plans' },
    { label: 'FAQ', href: '#faq' },
  ],
  hero: {
    proofTitle: '43 AI models',
    proofLink: { label: 'See what Dabba can do', href: '#features' },
    headline: 'Dabba',
    headlineMark: 'AI',
    subheadline: [
      'One workspace for chat, code and automation.',
      'Every major model, running on your own server.',
    ],
    badgeTitle: 'Claude, GPT, Gemini',
    badgeText: 'and NVIDIA in one chat',
    badgeAside: 'Self hosted',
    primaryCta: 'Try Dabba',
    secondaryCta: 'Create an account',
  },
  panel: {
    chips: [
      { text: 'Explain this stack trace', tone: 'orange' },
      { text: 'Draft the weekly status report', tone: 'blue' },
    ],
    stat: { label: 'Choose from', value: '43', caption: 'models from 8 providers. Switch any time.' },
    task: { title: 'Weekly status report', schedule: 'Mondays at 9:00', status: 'Scheduled', result: 'Done' },
  },
  worksWith: ['Anthropic', 'OpenAI', 'Google', 'NVIDIA', 'Ollama'],
  features: [
    {
      title: 'Every model in one chat',
      text: 'Pick Claude, GPT, Gemini, NVIDIA, Hugging Face or a local model, or let Auto choose. Change models mid conversation.',
    },
    {
      title: 'Agents and connectors',
      text: 'Hand off a task to an agent that plans, calls tools and reports back. Connect GitHub, Drive, Slack and 57 more tools.',
    },
    {
      title: 'Skills on a schedule',
      text: 'Save instructions you use often as skills, then run them every morning, every Monday or whenever you need.',
    },
  ],
  capabilities: [
    { title: 'Projects', text: 'Group chats, files and instructions by project so every piece of work keeps its context.' },
    { title: 'Agents and subagents', text: 'Define agents with their own prompt, model and allowed tools, and let them hand work to each other.' },
    { title: 'Cowork', text: 'Hand off a whole task, watch the activity as it runs, and get a report back when it is done.' },
    { title: 'Artifacts and documents', text: 'Preview code and documents next to the chat, then export to Word, Excel, PowerPoint or PDF.' },
    { title: 'Voice input', text: 'Dictate a prompt with your microphone instead of typing it.' },
    { title: 'Memory', text: 'Save facts and preferences you want Dabba to remember across conversations.' },
    { title: 'Approvals and hooks', text: 'Choose whether each tool asks first, runs on its own or is blocked, and add hooks around tool calls.' },
    { title: 'Task center', text: 'Follow every agent run, retry and approval in one place.' },
  ],
  models: {
    title: 'The models and tools you already use',
    text: 'Dabba puts hosted and local models behind one chat. Switch whenever a different model suits the job.',
    providers: [
      { name: 'Anthropic', family: 'Claude' },
      { name: 'OpenAI', family: 'GPT' },
      { name: 'Google', family: 'Gemini' },
      { name: 'NVIDIA', family: 'Hosted open models' },
      { name: 'Hugging Face', family: 'Open models' },
      { name: 'Ollama', family: 'Local models' },
      { name: 'Dabba', family: 'Small built in model' },
    ],
    connectorsTitle: 'Connect your apps',
    connectorsText: 'The connector catalogue offers 60 tools through MCP. Your agents can read from them and act in them, within the permissions you approve.',
    connectors: ['GitHub', 'Google Drive', 'Google Docs', 'Microsoft 365', 'Slack', 'Notion', 'Jira', 'Gmail'],
  },
  security: [
    { title: 'Keys stay on the server', text: 'Provider keys are stored encrypted on your server and are never sent to the browser.' },
    { title: 'You own the workspace', text: 'The first account becomes the owner. Running code, Cowork, hooks and connectors are limited to the owner.' },
    { title: 'Approval before action', text: 'Set each tool to ask first, run automatically or stay blocked, and review what ran afterwards.' },
    { title: 'Backups that survive restarts', text: 'Optionally copy the database to object storage so your data outlives a redeploy. Deploy with Docker or Render.' },
  ],
  steps: [
    { title: 'Ask anything', text: 'Chat, write code, upload files and preview artifacts in one place.' },
    { title: 'Connect your tools', text: 'Add connectors so Dabba can read and act in the apps you already use.' },
    { title: 'Automate the routine', text: 'Turn a good prompt into a skill and schedule it to run on its own.' },
  ],
  stats: [
    { value: '43', label: 'AI models' },
    { value: '8', label: 'Model providers' },
    { value: '60', label: 'Connectors' },
    { value: '1', label: 'Server you control' },
  ],
  quote: {
    text: 'Provider keys stay on the server and are never sent to the browser. Your chats stay on your Dabba server.',
    source: 'How Dabba is built',
  },
  plans: [
    {
      name: 'Try',
      tag: 'No account',
      summary: 'A quick look before you sign up.',
      points: ['Plain chat with the Auto model', 'Nothing to install', 'No files, tools or agents'],
      cta: 'Try Dabba',
      target: 'try',
    },
    {
      name: 'Personal',
      tag: 'Your account',
      summary: 'Your own space on a Dabba server.',
      points: ['All 43 models with your provider keys', 'Projects, files and artifacts', 'Saved and scheduled skills'],
      cta: 'Create an account',
      target: 'signup',
      featured: true,
    },
    {
      name: 'Workspace',
      tag: 'Self hosted',
      summary: 'Run Dabba for yourself or your team.',
      points: ['First account becomes the owner', 'Connectors, Cowork and hooks', 'Deploy with Docker or Render'],
      cta: 'Get started',
      target: 'signup',
    },
  ],
  faqs: [
    {
      q: 'What is Dabba?',
      a: 'Dabba is an AI workspace you run on your own server. It puts models from Anthropic, OpenAI, Google, NVIDIA, Hugging Face and Ollama behind one chat, with agents, connectors, saved skills, projects and scheduled automations.',
    },
    {
      q: 'Which AI models can I use?',
      a: 'The model picker lists 43 models from 8 providers, including Claude, GPT, Gemini, NVIDIA and local models through Ollama. Auto picks one for you.',
    },
    {
      q: 'Does Dabba connect to the tools I already use?',
      a: 'Yes. The connector catalogue offers 60 tools through MCP, including GitHub, Google Drive, Microsoft 365, Slack, Notion, Jira and Gmail.',
    },
    {
      q: 'What can agents do?',
      a: 'An agent plans a task, calls tools and connected apps, and reports back. You choose whether each tool asks for approval first, runs automatically or is blocked.',
    },
    {
      q: 'Can I run models on my own machine?',
      a: 'Yes. Dabba works with Ollama and other local models on the server, so chats with those models stay on your own server. Hosted models need provider keys.',
    },
    {
      q: 'Can I export my work?',
      a: 'Yes. Export your conversations as JSON from Settings, and export documents you create as Word, Excel, PowerPoint or PDF files.',
    },
    {
      q: 'Where is my data stored?',
      a: 'On the server that runs Dabba. Provider keys stay there and are never sent to the browser. Messages go only to the model provider you choose.',
    },
    {
      q: 'Who can run code, connectors and hooks?',
      a: 'Features that run commands on the server, such as running code, Cowork, hooks and connectors, are limited to the workspace owner.',
    },
    {
      q: 'How do I deploy Dabba?',
      a: 'Build the Docker image and run it on any host, or deploy to Render. The README covers the environment variables and backups.',
    },
  ],
  finalCta: {
    title: 'Bring every model into one workspace.',
    text: 'Start with a few questions, or create an account and set up your own Dabba.',
  },
}
