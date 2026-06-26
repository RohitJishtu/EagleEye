from etl.pipeline import load_pipeline

def run_job(name):
    cfg = build_config(name)
    return load_pipeline(cfg)

class Job:
    def execute(self):
        return run_job("default")

s = "def fake_function(): pass"
