# OLX.pl Technical Reconnaissance

## Date

2026-09-09 (Europe/Warsaw).

## Requests performed

### Direct HTTP reconnaissance (previous run)

| Requested URL | Final URL | HTTP status | Content-Type |
| --- | --- | --- | --- |
| https://www.olx.pl/elektronika/telefony/smartfony-telefony-komorkowe/iphone/ | same | 403 | text/html |

The response was a CloudFront blocked-request page. No OLX application data or canonical URL was available, and network reconnaissance stopped immediately.

## Offline browser-source reconnaissance

No network requests were performed in this phase. Analysis used only the supplied local files:

| Role | Local source | Recorded URL |
| --- | --- | --- |
| Search | samples/olx_search_source.html.html | https://www.olx.pl/elektronika/telefony/smartfony-telefony-komorkowe/iphone/ |
| Detail | samples/olx_detail_source.html.html | https://www.olx.pl/d/oferta/iphone-13-zielony-100-sprawny-CID99-ID1c8cXW.html?search_reason=search%7Corganic |

The files are Chrome view-source documents. The OLX original HTML was reconstructed in memory from their line cells; the sources were not altered.

## Search page findings

The source contains a canonical link to the search URL and 52 listing cards. Actual DOM fallback targets:

    [data-testid="l-card"][data-cy="l-card"]
      [data-testid="card-title-link"]
      [data-testid="ad-card-title"]
      [data-testid="ad-price"]
      [data-testid="location-date"]

Every card has a decimal HTML id. Location-date combines location with Polish human-readable refresh text.

## Structured data

The inline script with id olx-init-config assigns window.__PRERENDERED_STATE__ as a JSON-escaped JavaScript string. Decode that assignment, then decode its JSON value.

Search collection:

    window.__PRERENDERED_STATE__
      → listing → listing → ads[]     (52 objects)

Detail object:

    window.__PRERENDERED_STATE__
      → ad → ad

The complete ad objects on both paths contain:

    id, url, urlPath, title, price, location, createdTime, lastRefreshTime,
    isBusiness, description, photos, itemCondition, params, delivery,
    promotion, isPromoted, user, contact

Important nested fields:

    price.regularPrice.value
    price.regularPrice.currencyCode
    price.regularPrice.negotiable
    location.cityName / regionName / districtName / pathName
    params[].key / value / normalizedValue
    delivery.rock.active / mode

This is embedded browser state, not a public JSON endpoint.

Search source also contains three JSON-LD scripts: WebPage, Product, and BreadcrumbList. The Product script has offers.offers[] with 20 Offer objects. It supplies name, price, priceCurrency, url, image, itemCondition, areaServed, and priceValidUntil, but does not cover all 52 ads and lacks numeric ID, createdTime, and isBusiness.

Application/json scripts named __LOADABLE_REQUIRED_CHUNKS__ contain JavaScript chunk metadata only. No Next.js, Apollo cache, or Redux state was found.

## Listing detail findings

The detail embedded object agrees with the matching search object and its Product JSON-LD. Actual stable detail DOM fallback targets:

    [data-testid="offer_title"]
    [data-testid="ad-price-container"]
    [data-testid="ad-posted-at"]
    [data-testid="ad_description"]
    [data-testid="ad-parameters-container"]
    [data-testid="seller_card"]
    [data-testid="image-galery-container"]
    [data-testid="ad-photo"] img
    [data-testid="swiper-image"], [data-testid="swiper-image-lazy"]

Detail Product JSON-LD provides name, image[], url, description, sku, offers.price, offers.priceCurrency, offers.areaServed, and offers.itemCondition. It is a validation source, not a complete contract.

## External ID

    external_id source: listing.listing.ads[].id; ad.ad.id
    format: decimal numeric OLX ad ID, serialized as a string for Listing
    confidence: HIGH

The sampled listing ID is 1095405331. It is corroborated by the search-card HTML id and detail JSON-LD sku. The URL component ID1c8cXW is not preferred because the decimal ID is directly provided by OLX.

## Filters

Confirmed definitions at listing.listing.metaData.filters:

| Filter | Confirmed identifier or values | URL query parameter |
| --- | --- | --- |
| price range | filter_enum_price, filter_float_price; type price | UNKNOWN |
| condition | filter_enum_state: new, refurbished, damaged, used | UNKNOWN |
| model | filter_enum_phonemodel | UNKNOWN |
| storage | filter_enum_builtinmemory_phones | UNKNOWN |
| location | HTML input name location-Field | UNKNOWN |
| voivodeship | metaData.facets.region has region IDs and path URLs | UNKNOWN |
| district | no confirmed definition | UNKNOWN |
| private/business | no confirmed definition | UNKNOWN |

The visible price controls are range-from-input and range-to-input, but generic control names do not confirm public URL parameters. Do not infer price_from or price_to.

## Pagination

Server-rendered pagination exists at pagination-wrapper, data-cy pagination, NexusPagination, and pagination-forward. Confirmed next URL:

    /elektronika/telefony/smartfony-telefony-komorkowe/iphone/?page=2

Mechanism: numbered page query parameter.

## Anti-bot observations

The previous direct HTTP request received CloudFront 403. Browser sources show that complete data is present in initial source, but do not resolve that direct-access block. No CAPTCHA, Turnstile, proxy, endpoint, Playwright, or bypass attempt was made.

## Field availability

| Field | Search source | Detail source | Best source | Confidence |
| --- | --- | --- | --- | --- |
| external_id | ads[].id | ad.ad.id; JSON-LD sku validates | embedded state | HIGH |
| url | ads[].url / urlPath | same; canonical and JSON-LD validate | embedded state | HIGH |
| title | ads[].title | ad.ad.title; offer_title; JSON-LD name | embedded state | HIGH |
| price | ads[].price.regularPrice | same; JSON-LD validates | embedded state | HIGH |
| location | ads[].location | same; JSON-LD areaServed | embedded state | HIGH |
| seller_type | ads[].isBusiness | ad.ad.isBusiness; private parameter | embedded state | HIGH |
| published_at | ads[].createdTime ISO | same; DOM only has relative refresh text | embedded state | HIGH |
| description | ads[].description HTML | ad.ad.description; DOM and JSON-LD validate | embedded state | HIGH |
| photo_urls | ads[].photos[] | ad.ad.photos[]; gallery and JSON-LD validate | embedded state | HIGH |

CreatedTime is the publication/creation timestamp. LastRefreshTime is separate. The DOM posted-at value is Polish refresh text and has no time datetime attribute.

## Photos

The matching search and detail objects both have photos[] containing four distinct images. Detail DOM has all four, with size-transformed URLs such as ;s=667x1000 and additional srcset sizes. JSON-LD image[] has the same base URLs without a size suffix. The source does not prove that unqualified URLs are original/full-resolution assets. Use photos[] as supplied. No images were downloaded.

## Description

The full description is present before client-side interaction at ad.ad.description as an HTML string. It also exists at listing.listing.ads[].description and is rendered in the DOM at ad_description. The text is not reproduced here.

## Seller type

    isBusiness false → private
    isBusiness true  → business

The sample has isBusiness false and visible Prywatne, corroborating the mapping. user.sellerType is null in the sample and must not be used.

## Additional flip-relevant fields

Observed but not added to models:

- params[] includes condition, model, storage, and color with stable keys and normalized values;
- price.regularPrice.negotiable;
- delivery.rock.active and mode;
- isPromoted, isHighlighted, and promotion;
- seller account creation/last-seen, verification, contact capability, and additional-ad availability.

## Recommended parsing strategy

| Operation | A — preferred | B — fallback | C — last resort |
| --- | --- | --- | --- |
| search() | decoded __PRERENDERED_STATE__.listing.listing.ads[] | l-card DOM data-testid fields | category Product JSON-LD offers.offers[] |
| fetch_details() | decoded __PRERENDERED_STATE__.ad.ad | detail DOM data-testid fields | detail Product JSON-LD |

Recommended targets for the next implementation:

1. Extract olx-init-config and decode window.__PRERENDERED_STATE__.
2. Use listing.listing.ads[] for search and ad.ad for detail.
3. Read id, url, title, price.regularPrice, location, createdTime, isBusiness, description, and photos directly.
4. Use params[].key and normalizedValue for device attributes.
5. Retain data-testid DOM targets only as validation/fallback. Do not use generated css classes.

Avoid an undocumented internal JSON endpoint: initial source already has the complete objects and no endpoint behavior was verified.

## Playwright requirement

    Playwright required for search: NO
    Playwright required for detail: NO

Both complete objects are in the initial browser source. Playwright was not installed or used to work around the 403.

## Risks / unstable elements

- __PRERENDERED_STATE__ is an undocumented frontend contract; use defensive parsing and tests when implementation begins.
- Direct HTTP access from this environment is still blocked.
- URL token IDs, generated CSS classes, relative Polish dates, and partial JSON-LD are not primary contracts.
- Filter state identifiers do not prove public URL parameter names.

## Next implementation recommendation

A future OLX parser should first decode embedded state, retain data-testid DOM fields as fallback, and handle direct-access blocks explicitly. Production parser implementation is intentionally deferred.
