-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.tcg_card_prices (
  id bigint NOT NULL DEFAULT nextval('tcg_card_prices_id_seq'::regclass),
  set_code text NOT NULL,
  product_name text NOT NULL,
  card_number text,
  printing text,
  condition text,
  rarity text,
  market_price numeric,
  scraped_at timestamp with time zone DEFAULT now(),
  CONSTRAINT tcg_card_prices_pkey PRIMARY KEY (id),
  CONSTRAINT tcg_card_prices_set_code_fkey FOREIGN KEY (set_code) REFERENCES public.tcg_sets(set_code)
);
CREATE TABLE public.tcg_sets (
  id bigint NOT NULL DEFAULT nextval('tcg_sets_id_seq'::regclass),
  set_name text NOT NULL,
  set_code text NOT NULL UNIQUE,
  url text,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT tcg_sets_pkey PRIMARY KEY (id)
);