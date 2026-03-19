.PHONY: run dry-run metrics backtest notebook lint test install

run:
	python bot.py

dry-run:
	DRY_RUN=true python bot.py

metrics:
	python -m metrics.calculator --log logs/trades.jsonl

backtest:
	python -m backtest.engine --days 30

notebook:
	jupyter notebook notebooks/backtest.ipynb

lint:
	black . && flake8 .

test:
	pytest tests/ -v

install:
	pip install -r requirements.txt
