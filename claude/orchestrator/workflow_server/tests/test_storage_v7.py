"""Test Claude storage layer with schema v7."""
import pytest
import sqlite3
import tempfile
import os
from orchestrator.workflow_server.storage import Storage, SCHEMA_VERSION


class TestStorageV7:
    """Test schema v7 storage."""

    def test_schema_version(self):
        """Verify schema v7."""
        assert SCHEMA_VERSION == 7

    def test_fresh_database(self):
        """Test creating fresh v7 database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            storage = Storage(db_path)
            
            cur = storage.conn.cursor()
            cur.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
            version = cur.fetchone()[0]
            assert version == 7

    def test_session_metadata_v7(self):
        """Test v7 session metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            storage = Storage(db_path)
            
            sid = storage.create_session("TestProject")
            storage.set_mcp_client("claude-mcp")
            storage.set_phase("phase_2_interview", "asking_questions")
            storage.set_spec_frozen_at(123456.789)
            
            meta = storage.get_session_metadata()
            assert meta[4] == "claude-mcp"
            assert meta[5] == "phase_2_interview"
            assert meta[6] == "asking_questions"
            assert meta[7] == 123456.789

    def test_proposals_with_score(self):
        """Test proposals with score."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            storage = Storage(db_path)
            storage.create_session("Test")
            
            storage.add_proposal("oop", "# OOP Design", 92.5)
            storage.add_proposal("functional", "# Functional", 85.0)
            
            proposals = storage.list_proposals()
            assert len(proposals) == 2
            
            scores = {p[1]: p[3] for p in proposals}
            assert scores["oop"] == 92.5
            assert scores["functional"] == 85.0

    def test_artifacts(self):
        """Test artifact tracking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            storage = Storage(db_path)
            storage.create_session("Test")
            
            storage.add_artifact("task1", "src/auth.py", "create", "new file")
            storage.add_artifact("task1", "tests/test.py", "create")
            
            artifacts = storage.list_artifacts_for_task("task1")
            assert len(artifacts) == 2

    def test_background_jobs(self):
        """Test background job tracking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            storage = Storage(db_path)
            storage.create_session("Test")
            
            job_id = storage.create_background_job("bisset-architect")
            storage.update_background_job(job_id, "running")
            storage.update_background_job(job_id, "completed", {"proposals": 3})
            
            job = storage.get_background_job(job_id)
            assert job["status"] == "completed"
            assert job["result"]["proposals"] == 3

    def test_backward_compatibility_v6_to_v7(self):
        """Test auto-migration from v6 to v7."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "v6.db")
            
            # Create v6 database
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            
            cur.execute("CREATE TABLE schema_version (version INTEGER)")
            cur.execute("INSERT INTO schema_version VALUES (6)")
            
            cur.execute('''CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                name TEXT,
                created_at REAL,
                updated_at REAL
            )''')
            
            cur.execute('INSERT INTO sessions VALUES ("s1", "Test", 100.0, 100.0)')
            conn.commit()
            conn.close()
            
            # Load with v7 code
            storage = Storage(db_path)
            
            # Verify migration
            cur = storage.conn.cursor()
            cur.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
            assert cur.fetchone()[0] == 7
            
            # Verify data intact
            cur.execute('SELECT name FROM sessions WHERE id="s1"')
            assert cur.fetchone()[0] == "Test"
            
            # Verify new columns exist
            cur.execute("PRAGMA table_info(sessions)")
            cols = {row[1] for row in cur.fetchall()}
            assert {"mcp_client", "phase", "sub_phase", "spec_frozen_at"}.issubset(cols)

