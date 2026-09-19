#!/bin/bash
# Идемпотентно создаёт топики Kafka, используемые платформой.
# Запускается одноразовым контейнером kafka-init из docker-compose.
set -e

BROKER="kafka:9092"

# Находим kafka-topics.sh: в официальном образе apache/kafka он лежит в
# /opt/kafka/bin и НЕ добавлен в PATH, в bitnami — в /opt/bitnami/kafka/bin.
KT=""
for candidate in /opt/kafka/bin/kafka-topics.sh /opt/bitnami/kafka/bin/kafka-topics.sh; do
  if [ -x "$candidate" ]; then
    KT="$candidate"
    break
  fi
done
if [ -z "$KT" ] && command -v kafka-topics.sh >/dev/null 2>&1; then
  KT="kafka-topics.sh"
fi
if [ -z "$KT" ]; then
  echo "kafka-topics.sh not found in image" >&2
  exit 1
fi
echo "Using $KT"

TOPICS=(
  "booking.created:3:1"
  "booking.confirmed:3:1"
  "booking.cancelled:3:1"
  "payment.completed:3:1"
  "payment.failed:3:1"
  "review.submitted:3:1"
)

echo "Waiting for Kafka broker at $BROKER ..."
until "$KT" --bootstrap-server "$BROKER" --list > /dev/null 2>&1; do
  sleep 2
done

for entry in "${TOPICS[@]}"; do
  IFS=":" read -r name partitions replication <<< "$entry"
  echo "Creating topic: $name (partitions=$partitions, replication=$replication)"
  "$KT" --bootstrap-server "$BROKER" \
    --create --if-not-exists \
    --topic "$name" \
    --partitions "$partitions" \
    --replication-factor "$replication"
done

echo "All topics ready:"
"$KT" --bootstrap-server "$BROKER" --list
