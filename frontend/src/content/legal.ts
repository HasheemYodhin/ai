/**
 * Privacy policy and terms of use for the public pages (/privacy, /terms).
 *
 * The "what Dabba does" statements below were written from how the software
 * actually behaves (what it stores, where, and which services it talks to).
 * The legal wording around them, and every [PLACEHOLDER], must be completed
 * and approved by qualified legal counsel before this is published as final.
 * Set `LEGAL_REVIEWED` to true once that has happened; until then the pages
 * show a "draft" notice.
 *
 * Placeholders to fill in: COMPANY_NAME, CONTACT_EMAIL, EFFECTIVE_DATE,
 * HOSTING_PROVIDER, MINIMUM_AGE, JURISDICTION and the counsel-supplied
 * clauses marked in the text.
 */

export const LEGAL_REVIEWED = false

/** A block is a paragraph (string) or a bullet list (string[]). */
export type LegalBlock = string | string[]

export interface LegalSection {
  id: string
  title: string
  blocks: LegalBlock[]
}

export interface LegalDocument {
  title: string
  summary: string
  updated: string
  sections: LegalSection[]
}

export const PRIVACY: LegalDocument = {
  title: 'Privacy policy',
  summary: 'What Dabba stores, where it is stored, and who it is shared with.',
  updated: '[EFFECTIVE_DATE]',
  sections: [
    {
      id: 'who-we-are',
      title: 'Who we are',
      blocks: [
        'Dabba is a self hosted AI workspace for chat, code and automation. This policy describes how this Dabba service, operated by [COMPANY_NAME] ("we", "us"), handles information.',
        'You can reach us about privacy at [CONTACT_EMAIL].',
      ],
    },
    {
      id: 'information-we-collect',
      title: 'Information we collect',
      blocks: [
        'What we hold depends on whether you use Dabba as a guest or with an account.',
        [
          'Account details: your name, your email address and your password. The password is stored only as a salted PBKDF2 SHA 256 hash, never in plain text.',
          'Sign in sessions: a session token that keeps you signed in.',
          'Work you create: projects, skills, scheduled tasks, Cowork items, agent definitions, saved memories and files you add, stored on the Dabba server.',
          'Provider API keys you add: stored encrypted on the server and never sent back to your browser.',
          'Usage records: which model was used and token counts, plus an audit log of sensitive actions such as sign in and changes to settings.',
          'Technical data: your IP address and standard request details, used to run and protect the service.',
        ],
        'Guests (no account): Dabba keeps a random guest identifier and counts how many free prompts that identifier and your network address have used, so the free limit can be enforced. The text of guest prompts and replies is not saved by Dabba.',
      ],
    },
    {
      id: 'conversations',
      title: 'Your conversations',
      blocks: [
        'Conversation history is saved in your browser, on the device you use. It is not uploaded to the Dabba server for storage. You can export or clear it at any time from Settings, then Data Controls.',
        'Your messages are sent to the Dabba server, and from there to the AI model you chose, so that the model can reply.',
        'Voice input: if you use the microphone, your recording is sent to the Dabba server and turned into text there by a speech model that runs on the server. The recording is deleted as soon as it has been transcribed, and only the resulting text is used as your message.',
      ],
    },
    {
      id: 'ai-providers',
      title: 'AI model providers',
      blocks: [
        'To answer you, Dabba sends your messages, and any files or images you attach, to the provider of the model you pick. Depending on your choice this is Anthropic, OpenAI, Google, NVIDIA or Hugging Face, or a local Ollama model running on the server itself.',
        'Guests are answered by a model hosted by NVIDIA, shown in the app only as "Auto".',
        'Each provider handles that data under its own terms and privacy policy. We do not control how they process it, so please read theirs before sending sensitive information.',
      ],
    },
    {
      id: 'connectors',
      title: 'Connected apps',
      blocks: [
        'If the workspace owner connects apps such as GitHub, Google Drive, Microsoft 365, Slack, Notion, Jira or Gmail, Dabba can read from and act in them on your behalf, only within the permissions you approve. Information from those apps may be sent to the model you are chatting with.',
      ],
    },
    {
      id: 'how-we-use-it',
      title: 'How we use information',
      blocks: [
        [
          'To provide the service: sign you in, run chats, agents, skills and scheduled tasks.',
          'To keep it safe: enforce free prompt limits, prevent abuse and investigate problems.',
          'To improve reliability: for example by looking at errors and usage counts.',
        ],
        'We do not sell your personal information, and Dabba does not include advertising or third party analytics trackers.',
      ],
    },
    {
      id: 'cookies-storage',
      title: 'Cookies and browser storage',
      blocks: [
        'Dabba does not set cookies. It uses your browser\'s local storage for these items:',
        [
          'dabba-session-token: keeps you signed in.',
          'dabba-conversations: your saved chats.',
          'dabba-settings: your preferences.',
          'dabba-theme: your light or dark choice.',
          'A random guest identifier, used only to count free prompts.',
        ],
        'You can remove all of these by clearing site data in your browser. Doing so signs you out and deletes chats saved on that device.',
      ],
    },
    {
      id: 'sharing',
      title: 'Who we share information with',
      blocks: [
        [
          'The AI model providers and connected apps described above, only as needed to answer your requests.',
          'Our hosting and infrastructure provider, [HOSTING_PROVIDER], which runs the server that stores account data.',
          'Backup storage, if the operator turns it on: the database can be copied to object storage so it survives restarts.',
          'Authorities, where we are legally required to.',
        ],
      ],
    },
    {
      id: 'security-retention',
      title: 'Security and retention',
      blocks: [
        'We protect data with hashed passwords, encrypted provider keys, security headers and sign in sessions that expire. No system is perfectly secure, so we cannot guarantee absolute security.',
        'Account data stays until it is deleted. Guest counters are kept so the free limit keeps working. Chats saved in your browser stay until you clear them. [RETENTION_PERIODS: to be confirmed by legal counsel.]',
      ],
    },
    {
      id: 'your-choices',
      title: 'Your choices and rights',
      blocks: [
        [
          'Export or delete your saved chats yourself from Settings, then Data Controls.',
          'Ask us to correct, export or delete your account data at [CONTACT_EMAIL]. [ACCOUNT_DELETION_PROCESS: to be confirmed.]',
          'Use Dabba as a guest if you prefer not to create an account.',
        ],
        '[PRIVACY_RIGHTS_BY_REGION: rights that apply in your location, and how to use them, to be supplied by legal counsel.]',
      ],
    },
    {
      id: 'children',
      title: 'Children',
      blocks: ['Dabba is not meant for people under [MINIMUM_AGE]. If you believe a child has given us personal information, contact us at [CONTACT_EMAIL] and we will look into it.'],
    },
    {
      id: 'changes',
      title: 'Changes to this policy',
      blocks: ['We may update this policy as Dabba changes. The date at the top shows the latest version, and we will point out significant changes in the app.'],
    },
    {
      id: 'contact',
      title: 'Contact',
      blocks: ['Questions about this policy: [CONTACT_EMAIL]. Operator: [COMPANY_NAME].'],
    },
  ],
}

export const TERMS: LegalDocument = {
  title: 'Terms of use',
  summary: 'The rules for using Dabba, as a guest or with an account.',
  updated: '[EFFECTIVE_DATE]',
  sections: [
    {
      id: 'acceptance',
      title: 'Accepting these terms',
      blocks: ['By using Dabba, as a guest or with an account, you agree to these terms and to our privacy policy. If you do not agree, please do not use the service.'],
    },
    {
      id: 'the-service',
      title: 'The service',
      blocks: [
        'Dabba is an AI workspace operated by [COMPANY_NAME]. It lets you chat with AI models and, with an account, use projects, agents, connected apps, saved skills and scheduled automations.',
        'Which features and models you can use depends on how the operator has set up the server, including which provider keys are available.',
      ],
    },
    {
      id: 'accounts',
      title: 'Accounts',
      blocks: [
        [
          'Give accurate details and keep your password private. You are responsible for what happens under your account.',
          'The first account created on a Dabba server becomes the workspace owner. Features that run commands on the server, such as running code, Cowork, hooks and connectors, are limited to the owner.',
          'Tell us at [CONTACT_EMAIL] if you think your account has been accessed without your permission.',
        ],
      ],
    },
    {
      id: 'guest-access',
      title: 'Free guest access',
      blocks: [
        'Visitors without an account get a small number of free prompts. The limit is counted per browser and per network address, and it can change or be switched off at any time.',
        'Guest chat is plain text chat only. Guests cannot use tools, files, agents or code execution. Do not try to get around the limit.',
      ],
    },
    {
      id: 'acceptable-use',
      title: 'Acceptable use',
      blocks: [
        'You agree not to:',
        [
          'break the law or break the rights of others;',
          'send content you have no right to share, including other people\'s personal information;',
          'try to disrupt, overload or probe the service, or get around its limits and security;',
          'use Dabba to build malware, harass people or create content that harms others;',
          'resell or give others access to the service in ways the operator has not allowed.',
        ],
      ],
    },
    {
      id: 'ai-content',
      title: 'AI generated content',
      blocks: [
        'AI models can be wrong, out of date or incomplete. Check anything important, such as legal, medical, financial or security matters, before relying on it.',
        'You are responsible for how you use the output, including any code you run and any actions an agent takes with the apps you connected.',
      ],
    },
    {
      id: 'your-content',
      title: 'Your content',
      blocks: [
        'You keep your rights in what you put into Dabba and in what you create with it. You give us the permission needed to process it in order to run the service for you, including sending it to the model provider you chose. [CONTENT_LICENSE_TERMS: wording to be supplied by legal counsel.]',
      ],
    },
    {
      id: 'third-parties',
      title: 'Third party services and costs',
      blocks: [
        'Models and connected apps are provided by other companies under their own terms, and you must follow those terms. Hosted models need provider keys, and the provider bills the key holder for what is used. Dabba does not set or collect those charges.',
      ],
    },
    {
      id: 'availability',
      title: 'Availability and changes',
      blocks: [
        'We work to keep Dabba running but cannot promise it will always be available or error free. We may change, limit or stop features, models or the free guest allowance, for example when a provider changes.',
      ],
    },
    {
      id: 'ending',
      title: 'Ending your use',
      blocks: ['You can stop using Dabba at any time. We may suspend or end access if these terms are broken or to protect the service or other people.'],
    },
    {
      id: 'liability',
      title: 'Warranties and liability',
      blocks: ['[WARRANTY_AND_LIABILITY_CLAUSES: to be drafted by qualified legal counsel.]'],
    },
    {
      id: 'law',
      title: 'Governing law',
      blocks: ['The laws of [JURISDICTION] apply to these terms. [GOVERNING_LAW_AND_DISPUTES: dispute resolution wording to be confirmed by legal counsel.]'],
    },
    {
      id: 'changes-contact',
      title: 'Changes and contact',
      blocks: [
        'We may update these terms. If you keep using Dabba after a change, that means you accept the new version.',
        'Questions: [CONTACT_EMAIL]. Operator: [COMPANY_NAME].',
      ],
    },
  ],
}
