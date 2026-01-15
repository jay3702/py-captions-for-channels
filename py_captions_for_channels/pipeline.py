import subprocess
import logging


class Pipeline:
    """
    Executes the captioning workflow.
    """

    def __init__(self, command_template: str):
        self.command_template = command_template

    def run(self, event):
        cmd = self.command_template.format(path=event.path)
        logging.info(f"Running caption pipeline: {cmd}")

        proc = subprocess.run(cmd, shell=True)
        if proc.returncode != 0:
            logging.error(f"Caption pipeline failed for {event.path}")
        else:
            logging.info(f"Caption pipeline completed for {event.path}")
