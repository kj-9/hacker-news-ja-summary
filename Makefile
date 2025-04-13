update:
	git add rss/*.xml
	git commit -m "Update RSS feed" || echo "No changes to commit"
	git push