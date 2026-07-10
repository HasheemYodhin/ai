#!/usr/bin/env node
/**
 * Fails the build if package.json's version hasn't changed since the last
 * successful `vsce package` run.
 *
 * There's no git repository here to compare against a tag, so the "last
 * published version" is tracked in .last-published-version instead — a
 * plain text file holding the version string as of the last successful
 * package script run (updated by record-version.js after vsce package
 * actually succeeds, not before).
 */
const fs = require('fs');
const path = require('path');

const pkgPath = path.join(__dirname, '..', 'package.json');
const lockPath = path.join(__dirname, '..', '.last-published-version');

const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
const currentVersion = pkg.version;

let lastPublished = null;
if (fs.existsSync(lockPath)) {
  lastPublished = fs.readFileSync(lockPath, 'utf8').trim();
}

if (lastPublished === currentVersion) {
  console.error(
    `\nRefusing to package: version ${currentVersion} matches the last published version.\n` +
    `Bump "version" in package.json before running "npm run package" again.\n`,
  );
  process.exit(1);
}

console.log(`Version check passed: ${currentVersion} (last published: ${lastPublished || 'none'})`);
