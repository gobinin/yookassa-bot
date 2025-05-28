#!/bin/bash

echo "📦 Добавляем изменения..."
git add .

echo "✏️ Введите комментарий к коммиту:"
read commit_msg

git commit -m "$commit_msg"

echo "🚀 Отправляем на GitHub..."
git push origin main

echo "✅ Готово! Railway автоматически обновит бота."
