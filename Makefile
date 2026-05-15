.PHONY: start agent monitor reset

start:
	docker run --rm -p 4222:4222 -p 8222:8222 nats:latest -js -m 8222

agent:
	.venv/bin/python3 agent.py \
		--name "$(or $(NAME), $(firstword $(prompt)))" \
		--prompt "$(prompt)"

monitor:
	.venv/bin/python3 monitor.py

reset:
	-pkill -f "agent\.py|monitor\.py" 2>/dev/null; \
	rm -f monitor.log alice.log bob.log *.log; \
	echo "Clean."
