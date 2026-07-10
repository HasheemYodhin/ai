#!/usr/bin/env node
/**
 * Records the current package.json version as "last published" after a
 * successful `vsce package` run. Only runs if vsce package exits 0 (see the
 * `package` script's use of `&&`), so a failed package never advances the
 * lock file.
 */
const fs = require('fs');
const path = require('path');

const pkgPath = path.join(__dirname, '..', 'package.json');
const lockPath = path.join(__dirname, '..', '.last-published-version');

const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
fs.writeFileSync(lockPath, pkg.version + '\n');
console.log(`Recorded published version: ${pkg.version}`);
