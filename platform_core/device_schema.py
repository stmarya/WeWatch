"""Additive v2 migration: session-bound browser enrollment; NOT desktop credentials."""
MIGRATION_2 = '''
CREATE TABLE IF NOT EXISTS browser_devices(
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
 user_id TEXT NOT NULL REFERENCES users(id), session_id TEXT NOT NULL REFERENCES account_sessions(id),
 name TEXT NOT NULL, role_at_pairing TEXT NOT NULL, created_at INTEGER NOT NULL,
 revoked_at INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS one_browser_per_session_workspace
 ON browser_devices(session_id,workspace_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS browser_devices_by_workspace ON browser_devices(workspace_id,user_id);
CREATE TABLE IF NOT EXISTS device_pairings(
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
 user_id TEXT NOT NULL REFERENCES users(id), session_id TEXT NOT NULL REFERENCES account_sessions(id),
 name TEXT NOT NULL, role_at_request TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
 created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, used_at INTEGER, revoked_at INTEGER
);
CREATE TABLE IF NOT EXISTS preview_consents(
 id TEXT PRIMARY KEY, device_id TEXT NOT NULL REFERENCES browser_devices(id),
 capability TEXT NOT NULL CHECK(capability IN ('camera_preview','microphone_preview')),
 policy_version TEXT NOT NULL, granted_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, revoked_at INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS one_preview_grant ON preview_consents(device_id,capability) WHERE revoked_at IS NULL;
CREATE TABLE IF NOT EXISTS browser_readiness(
 device_id TEXT PRIMARY KEY REFERENCES browser_devices(id),
 secure_context INTEGER NOT NULL, media_supported INTEGER NOT NULL,
 camera TEXT NOT NULL, microphone TEXT NOT NULL, updated_at INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS revoke_browser_consents AFTER UPDATE OF revoked_at ON browser_devices
 WHEN NEW.revoked_at IS NOT NULL BEGIN
 UPDATE preview_consents SET revoked_at=NEW.revoked_at WHERE device_id=NEW.id AND revoked_at IS NULL;
END;
CREATE TRIGGER IF NOT EXISTS revoke_browser_on_session AFTER UPDATE OF revoked_at ON account_sessions
 WHEN NEW.revoked_at IS NOT NULL BEGIN
 UPDATE browser_devices SET revoked_at=NEW.revoked_at WHERE session_id=NEW.id AND revoked_at IS NULL;
 UPDATE device_pairings SET revoked_at=NEW.revoked_at WHERE session_id=NEW.id AND revoked_at IS NULL;
END;
CREATE TRIGGER IF NOT EXISTS revoke_browser_on_role AFTER UPDATE OF role ON memberships
 WHEN OLD.role != NEW.role BEGIN
 UPDATE browser_devices SET revoked_at=strftime('%s','now') WHERE workspace_id=OLD.workspace_id AND user_id=OLD.user_id AND revoked_at IS NULL;
 UPDATE device_pairings SET revoked_at=strftime('%s','now') WHERE workspace_id=OLD.workspace_id AND user_id=OLD.user_id AND revoked_at IS NULL;
END;
CREATE TRIGGER IF NOT EXISTS revoke_browser_on_leave AFTER DELETE ON memberships BEGIN
 UPDATE browser_devices SET revoked_at=strftime('%s','now') WHERE workspace_id=OLD.workspace_id AND user_id=OLD.user_id AND revoked_at IS NULL;
 UPDATE device_pairings SET revoked_at=strftime('%s','now') WHERE workspace_id=OLD.workspace_id AND user_id=OLD.user_id AND revoked_at IS NULL;
END;
CREATE TRIGGER IF NOT EXISTS revoke_browser_on_disable AFTER UPDATE OF disabled_at ON users
 WHEN NEW.disabled_at IS NOT NULL BEGIN
 UPDATE browser_devices SET revoked_at=NEW.disabled_at WHERE user_id=NEW.id AND revoked_at IS NULL;
 UPDATE device_pairings SET revoked_at=NEW.disabled_at WHERE user_id=NEW.id AND revoked_at IS NULL;
END;
'''
