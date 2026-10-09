# PostgreSQL 18 + PostGIS 3.6 with the LKS-92 -> LKS-2020 grid (decision D9).
#
# The base image ships PROJ 9.8.1, which knows EPSG:10306 and EPSG:10838, but not
# the NTv2 grid that EPSG:10838 needs. Without the grid PROJ silently applies a
# null shift (~9.5 cm off at Odukalns), so the grid is baked in here and checked.
#
# Base pinned by digest (tag 18-3.6, pulled 2026-10-09). To update: pull the tag,
# take the new digest from `docker image inspect`, rebuild, run the CRS tests.
FROM postgis/postgis:18-3.6@sha256:60f6ad1d21ea86a67d47780b9a0d1e1d200500f62b19293fa834d0dea80b8677

# Grid: see README.md in this folder for source, licence and attribution.
ARG LKS_GRID=lv_lgia_lks92to2020.tif
ARG LKS_GRID_SHA256=6be363d4796bb3038e751da00e2344593edbb149ed193fc31b9c200688b31498

COPY ${LKS_GRID} /usr/share/proj/${LKS_GRID}
RUN echo "${LKS_GRID_SHA256}  /usr/share/proj/${LKS_GRID}" | sha256sum -c - \
    && chmod 0644 /usr/share/proj/${LKS_GRID}

# PROJ >= 9.8 is required for EPSG:10306 / EPSG:10838 (D9). Fail the build otherwise.
RUN v="$(dpkg-query -W -f='${Version}' libproj25)" \
    && echo "libproj25 ${v}" \
    && dpkg --compare-versions "${v}" ge 9.8

# Grids come only from the image, never downloaded at run time.
ENV PROJ_NETWORK=OFF

# Replace the base image's init script (it also installs the US TIGER geocoder,
# topology and fuzzystrmatch, plus a template_postgis DB); ours enables only
# postgis, pg_trgm and unaccent.
RUN rm /docker-entrypoint-initdb.d/10_postgis.sh
COPY initdb/ /docker-entrypoint-initdb.d/
