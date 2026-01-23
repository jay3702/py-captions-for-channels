#!/usr/bin/env python3
"""Add _load() calls to get_executions and get_execution methods"""

with open('py_captions_for_channels/execution_tracker.py', 'r') as f:
    content = f.read()

# Add _load() before get_executions lock
content = content.replace(
    '''    def get_executions(self, limit: int = 50) -> List[dict]:
        """Get recent executions, most recent first.

        Args:
            limit: Maximum number of executions to return

        Returns:
            List of execution dicts
        """
        with self.lock:''',
    '''    def get_executions(self, limit: int = 50) -> List[dict]:
        """Get recent executions, most recent first.

        Args:
            limit: Maximum number of executions to return

        Returns:
            List of execution dicts
        """
        # Reload from disk to see changes from other processes
        self._load()
        with self.lock:'''
)

# Add _load() before get_execution lock
content = content.replace(
    '''    def get_execution(self, job_id: str) -> Optional[dict]:
        """Get a specific execution by ID.

        Args:
            job_id: Job identifier

        Returns:
            Execution dict or None
        """
        with self.lock:''',
    '''    def get_execution(self, job_id: str) -> Optional[dict]:
        """Get a specific execution by ID.

        Args:
            job_id: Job identifier

        Returns:
            Execution dict or None
        """
        # Reload from disk to see changes from other processes
        self._load()
        with self.lock:'''
)

with open('py_captions_for_channels/execution_tracker.py', 'w') as f:
    f.write(content)

print('Updated execution_tracker.py')
