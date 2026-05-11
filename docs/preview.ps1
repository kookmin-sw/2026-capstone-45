docker run --rm -it `
  --volume="${PWD}:/srv/jekyll" `
  --publish 5002:4000 `
  -e PAGES_REPO_NWO=local/preview `
  jekyll/jekyll:latest `
  jekyll serve --watch --force_polling
