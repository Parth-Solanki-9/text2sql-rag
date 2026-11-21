.PHONY: setup demo test app api evaluate clean

setup:
	python -m pip install -r requirements.txt

demo:
	python scripts/init_demo_db.py

test:
	python -m pytest -q

app:
	streamlit run app.py

api:
	uvicorn src.text2sql.api:app --reload

evaluate:
	python scripts/evaluate.py

clean:
	python -c "from pathlib import Path; import shutil; [shutil.rmtree(p) for p in Path('.').rglob('__pycache__') if p.is_dir()]; shutil.rmtree('.pytest_cache', ignore_errors=True)"
