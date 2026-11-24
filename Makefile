PY ?= python3
EXAMPLES = RUT:1 PSA:22 PSA:23 PSA:136 EXO:15 EXO:39 LUK:1

.PHONY: help setup test test-js examples plans client cast cuts clean-output clean-cache

help:
	@echo "make setup         install, download the pinned data and build the cast table (once)"
	@echo "make examples      rebuild examples/ ($(EXAMPLES))"
	@echo "make test          run the tests (they also check that examples/ is current)"
	@echo "make plans         write the song plans of every book (plan/<BOOK>/, see plan/SCHEMA.md)"
	@echo "make client        build dist/config.json, the config the JS library reads"
	@echo "make test-js       the JS library gives examples/ byte for byte (needs plans and client)"
	@echo "make cast          rebuild the generated cast table (cache/cast/cast.csv, output/cast.csv)"
	@echo "make cuts          where chapters over 4000 characters can be cut (output/cut-points.txt)"
	@echo "$(PY) -m bible_song_builder BOOK CHAPTER...   build any chapter(s) into output/; 'all' for a whole book"

setup:
	$(PY) -m pip install -e .
	$(PY) scripts/build_cast.py

examples:
	$(PY) -c "import shutil; shutil.rmtree('examples', ignore_errors=True)"
	@for bc in $(EXAMPLES); do $(PY) -m bible_song_builder $${bc%%:*} $${bc##*:} --out examples --bare >/dev/null || exit 1; done
	@echo "examples/ rebuilt"

plans:
	$(PY) -m bible_song_builder.plan all

client:
	$(PY) -m bible_song_builder.client

test-js: client
	@for b in RUT PSA EXO LUK; do $(PY) -c "from bible_song_builder import plan; plan.ensure('$$b')"; done
	cd js && node --test test/*.test.mjs

cast:
	$(PY) scripts/build_cast.py

cuts:
	@mkdir -p output
	$(PY) scripts/cut_points.py > output/cut-points.txt
	@head -5 output/cut-points.txt

test:
	$(PY) -m unittest discover -s tests -v

clean-output:
	$(PY) -c "import shutil; shutil.rmtree('output', ignore_errors=True)"

clean-cache:
	$(PY) -c "import shutil; shutil.rmtree('cache', ignore_errors=True)"
