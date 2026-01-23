#!/usr/bin/env python3
"""Fix execution_tracker to reload from disk on get_executions/get_execution"""

# Read the file
with open('py_captions_for_channels/execution_tracker.py', 'r') as f:
    content = f.read()

# Find and replace get_executions method
old_get_executions = '''    def get_executions(self, limit: int = 50) -> List[dict]:
        """Get recent executions, most recent first.

        Args:
            limit: Maximum number of executions to return

        Returns:
            List of execution dicts
        """
        with self.lock:
            # Sort by started_at descending
            sorted_execs = sorted(
                self.executions.values(),
                key=lambda x: x.get("started_at", ""),
                reverse=True,
            )
            return sorted_execs[:limit]'''

new_get_executions = '''    def get_executions(self, limit: int = 50) -> List[dict]:
        """Get recent executions, most recent first.

        Args:
            limit: Maximum number of executions to return

        Returns:
            List of execution dicts
        """
        self._load()
        with self.lock:
            # Sort by started_at descending
            sorted_execs = sorted(
                self.executions.values(),
                key=lambda x: x.get("started_at", ""),
                reverse=True,
            )
            return sorted_execs[:limit]'''

content = content.replace(old_get_executions, new_get_executions)

# Find and replace get_execution method
old_get_execution = '''    def get_execution(self, job_id: str) -> Optional[dict]:
        """Get a specific execution by ID.

        Args:
            job_id: Job identifier

        Returns:
            Execution dict or None
        """
        with self.lock:
            return self.executions.get(job_id)'''

new_get_execution = '''    def get_execution(self, job_id: str) -> Optional[dict]:
        """Get a specific execution by ID.

        Args:
            job_id: Job identifier

        Returns:
            Execution dict or None
        """
        self._load()
        with self.lock:
            return self.executions.get(job_id)'''

content = content.replace(old_get_execution, new_get_execution)

# Write back
with open('py_captions_for_channels/execution_tracker.py', 'w') as f:
    f.write(content)

print("Updated execution_tracker.py to reload from disk on get_executions/get_execution")
