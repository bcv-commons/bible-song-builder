// The config bundle (dist/config.json, made by `python -m bible_song_builder.client`): config/
// parsed and checked. Mirrors bible_song_builder/config.py, profiles.py and the cast lookups of cast.py.
import { ConfigError, isObj } from './util.js';

export const VOICES = ['narrator', 'female', 'male', 'group', 'female_group', 'divine'];

/** a with b laid over it, table by table (config.merge) */
export function merge(a, b) {
    const out = { ...a };
    for (const [k, v] of Object.entries(b || {})) {
        out[k] = isObj(v) && isObj(out[k]) ? merge(out[k], v) : v;
    }
    return out;
}

export class Config {
    /** bundle: the parsed dist/config.json */
    constructor(bundle) {
        if (String(bundle.schema || '').split('.')[0] !== '1') throw new ConfigError(`config bundle schema ${bundle.schema}, this code reads 1.x`);
        this.bundle = bundle;
        this.pins = bundle.pins;
        this._layout = new Map();
    }

    toml(name) {
        const t = this.bundle.toml[name];
        if (!t) throw new ConfigError(`config/${name} is missing`);
        return t;
    }

    /** the edition's block of editions.toml ({} if none) */
    edition(name) {
        return name ? this.toml('editions.toml')[name] || {} : {};
    }

    language(iso) {
        return this.toml('languages.toml')[iso] || {};
    }

    /** layout.toml, then the language's [<iso>.layout], then the edition's [<EDITION>.layout] */
    layout(edition) {
        const key = edition ? `${edition.name}|${edition.iso}` : '';
        if (!this._layout.has(key)) {
            let out = this.toml('layout.toml');
            if (edition) {
                out = merge(out, edition.iso ? this.language(edition.iso).layout || {} : {});
                out = merge(out, this.edition(edition.name).layout || {});
            }
            this._layout.set(key, out);
        }
        return this._layout.get(key);
    }

    /** config/books/<BOOK>.toml over _default.toml (checked when the bundle was made) */
    book(code) {
        return this.bundle.books[code] || this.bundle.books._default;
    }

    hasOwnBook(code) {
        return code in this.bundle.books && code !== '_default';
    }

    castRules() {
        return this.toml('cast-rules.toml');
    }

    /** speaker_id -> {voice, name} */
    castTable() {
        return this.bundle.cast;
    }
}

/** The speaker's voice class: the cast table's, else ``rule`` (the plan's voice by the rules),
 *  else the rules' default (cast.voice_of with no SpeakerInfo). */
export function voiceOf(cfg, sid, rule = null) {
    const rules = cfg.castRules();
    if (!sid) return rules.unknown ?? 'narrator';
    const entry = cfg.castTable()[sid];
    if (entry && entry.voice) return entry.voice;
    return rule || (rules.default ?? 'male');
}

/** The cast table's readable name for a speaker (for the notes), if it has one */
export function castName(cfg, sid) {
    const entry = cfg.castTable()[sid || ''];
    return entry ? entry.name || null : null;
}

// ---- profiles (profiles.py) ----

const deepMerge = (a, b) => {
    const out = structuredClone(a ?? {});
    for (const [k, v] of Object.entries(b || {})) {
        out[k] = isObj(v) && isObj(out[k]) ? deepMerge(out[k], v) : structuredClone(v);
    }
    return out;
};

/** The song profile of a book in an edition (profiles.for_book) */
export function profileFor(cfg, edition, book, profile = null, lead = null) {
    const profs = cfg.toml('profiles.toml');
    const ed = cfg.toml('editions.toml')[edition.name] || {};
    let pick = {};
    const bc = cfg.book(book);
    const own = Object.fromEntries(['profile', 'lead', 'style'].filter((k) => k in bc).map((k) => [k, bc[k]]));
    for (const layer of [own, ed.default, (ed.books || {})[book]]) pick = deepMerge(pick, layer || {});
    const name = profile || pick.profile;
    lead = lead || pick.lead || 'male';
    const all = profs.profiles || {};
    if (!(name in all)) {
        throw new ConfigError(`config/books/${book}.toml (or _default.toml, editions.toml): book ${book} has profile '${name}', which is not in `
            + `config/profiles.toml; choose from ${Object.keys(all).join(', ')}`);
    }
    if (lead !== 'female' && lead !== 'male') throw new ConfigError(`config/books/${book}.toml: lead '${lead}'; use "female" or "male"`);
    const p = deepMerge(all[name], (ed.profiles || {})[name] || {});
    if (!p.style) throw new ConfigError(`config/profiles.toml: profile '${name}' has no style`);
    const tags = deepMerge(profs.tags || {}, p.tags || {});
    const unknown = Object.keys(tags).filter((t) => !VOICES.includes(t) && t !== 'refrain').sort();
    if (unknown.length) {
        throw new ConfigError(`config/profiles.toml: unknown voice tag name(s) ${unknown.join(', ')} (profile ${name}); `
            + `allowed: ${VOICES.join(', ')}, refrain`);
    }
    const suffix = ed.style_suffix || '';
    const base = pick.style || p.style;
    return {
        name, lead, style: base + suffix,
        persona: (p.persona || {})[lead] || null,
        tags, base_style: base, suffix,
        moods: deepMerge(profs.moods || {}, p.moods || {}),
        instruments: deepMerge(profs.instruments || {}, p.instruments || {}),
        families: deepMerge(profs.families || {}, p.families || {}),
        family_tag: p.family_tag ?? profs.family_tag ?? '[Mood: {words}]',
    };
}
