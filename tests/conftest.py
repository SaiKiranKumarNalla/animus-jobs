import os
import tempfile

# every test run gets its own empty data folder — never the user's real one
os.environ["JOBAGENT_HOME"] = tempfile.mkdtemp(prefix="jobagent-test-")
