from collections import defaultdict
from osgoe import osr
from osgeo import ogr

BIODIVERSITY_VECTOR_PATH = 'data/LANDSCAPES_JAGUAR_REGIONAL.shp'
ADMIN_VECTOR_ID_FIELD = 'iso3'
ADMIN_VECTOR_PATH = 'data/countries_iso3_md5_6fb2431e911401992e6e56ddf0a9bcda.gpkg'
PROTECTED_AREAS_FIELD = 'IUCN_CAT'
PROTECTED_AREAS_PATH = 'data/global-2024-05-08.gpkg'

SIMPLIFY_TOLERANCE = 0.001


def reproject_geometry(geom, target_srs):
    source_srs = geom.GetSpatialReference()
    if source_srs is None:
        raise ValueError("Source geometry has no spatial reference.")
    transform = osr.CoordinateTransformation(source_srs, target_srs)
    geom.Transform(transform)
    return geom


def main():
    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(3857)

    admin_ds = ogr.Open(ADMIN_VECTOR_PATH)
    admin_layer = admin_ds.GetLayer()
    admin_srs = admin_layer.GetSpatialRef()

    iso3_codes = set()
    for feature in admin_layer:
        iso3_code = feature.GetField(ADMIN_VECTOR_ID_FIELD)
        iso3_codes.add(iso3_code)
    admin_layer.ResetReading()

    bio_ds = ogr.Open(BIODIVERSITY_VECTOR_PATH)
    bio_layer = bio_ds.GetLayer()
    bio_srs = bio_layer.GetSpatialRef()

    pa_ds = ogr.Open(PROTECTED_AREAS_PATH)
    pa_layer = pa_ds.GetLayer()
    pa_srs = pa_layer.GetSpatialRef()

    iucn_cats = set()
    for feature in pa_layer:
        iucn_cat = feature.GetField(PROTECTED_AREAS_FIELD)
        iucn_cats.add(iucn_cat)
    pa_layer.ResetReading()

    results = defaultdict(dict)

    for iso3_code in iso3_codes:
        print(f"Processing ISO3 code: {iso3_code}")

        # Filter admin features by iso3 code
        admin_layer.SetAttributeFilter(f"{ADMIN_VECTOR_ID_FIELD} = '{iso3_code}'")

        # Merge geometries for the current iso3 code
        admin_geom = None
        for feature in admin_layer:
            geom = feature.GetGeometryRef()
            geom = geom.Clone()
            if admin_geom is None:
                admin_geom = geom
            else:
                admin_geom = admin_geom.Union(geom)
        admin_layer.ResetReading()

        if admin_geom is None:
            continue

        # Reproject admin geometry to target SRS
        admin_geom.AssignSpatialReference(admin_srs)
        admin_geom = reproject_geometry(admin_geom, target_srs)

        # Simplify geometry to improve performance
        admin_geom = admin_geom.SimplifyPreserveTopology(SIMPLIFY_TOLERANCE)

        # Create spatial filter for biodiversity layer
        bio_layer.SetSpatialFilter(admin_geom)

        # Calculate overlap area between admin area and biodiversity layer
        bio_overlap_area = 0.0
        for bio_feature in bio_layer:
            bio_geom = bio_feature.GetGeometryRef()
            bio_geom = bio_geom.Clone()
            bio_geom.AssignSpatialReference(bio_srs)
            bio_geom = reproject_geometry(bio_geom, target_srs)
            intersection = admin_geom.Intersection(bio_geom)
            bio_overlap_area += intersection.GetArea()
        bio_layer.ResetReading()

        # Convert area to hectares
        bio_overlap_area_ha = bio_overlap_area / 10000  # 1 hectare = 10,000 square meters
        results[iso3_code]['biodiversity_overlap_ha'] = bio_overlap_area_ha

        print(f"Overlap with biodiversity layer: {bio_overlap_area_ha:.2f} hectares")

        # Process each IUCN category
        for iucn_cat in iucn_cats:
            print(f"  Processing IUCN Category: {iucn_cat}")

            # Filter protected areas by IUCN category
            pa_layer.SetAttributeFilter(f"{PROTECTED_AREAS_FIELD} = '{iucn_cat}'")
            pa_layer.SetSpatialFilter(admin_geom)  # Spatially filter to admin area

            # Calculate overlap area between admin area and protected areas
            pa_overlap_area = 0.0
            bio_pa_overlap_area = 0.0
            for pa_feature in pa_layer:
                pa_geom = pa_feature.GetGeometryRef()
                pa_geom = pa_geom.Clone()
                pa_geom.AssignSpatialReference(pa_srs)
                pa_geom = reproject_geometry(pa_geom, target_srs)
                pa_geom = pa_geom.SimplifyPreserveTopology(SIMPLIFY_TOLERANCE)

                # Overlap with admin area
                intersection = admin_geom.Intersection(pa_geom)
                pa_overlap_area += intersection.GetArea()

                # Overlap with both admin area and biodiversity layer
                bio_pa_intersection_area = 0.0
                bio_layer.SetSpatialFilter(intersection)
                for bio_feature in bio_layer:
                    bio_geom = bio_feature.GetGeometryRef()
                    bio_geom = bio_geom.Clone()
                    bio_geom.AssignSpatialReference(bio_srs)
                    bio_geom = reproject_geometry(bio_geom, target_srs)
                    bio_pa_intersection = intersection.Intersection(bio_geom)
                    bio_pa_intersection_area += bio_pa_intersection.GetArea()
                bio_layer.ResetReading()

                bio_pa_overlap_area += bio_pa_intersection_area

            pa_layer.ResetReading()

            # Convert areas to hectares
            pa_overlap_area_ha = pa_overlap_area / 10000
            bio_pa_overlap_area_ha = bio_pa_overlap_area / 10000

            # Store results
            results[iso3_code][f'pa_overlap_ha_{iucn_cat}'] = pa_overlap_area_ha
            results[iso3_code][f'bio_pa_overlap_ha_{iucn_cat}'] = bio_pa_overlap_area_ha

            print(f"    Overlap with protected areas: {pa_overlap_area_ha:.2f} hectares")
            print(f"    Overlap with both biodiversity and protected areas: {bio_pa_overlap_area_ha:.2f} hectares")

        admin_layer.SetAttributeFilter(None)
        admin_layer.SetSpatialFilter(None)
        bio_layer.SetSpatialFilter(None)
        pa_layer.SetAttributeFilter(None)
        pa_layer.SetSpatialFilter(None)

    # Output results
    print("\nFinal Results:")
    for iso3_code, data in results.items():
        print(f"ISO3: {iso3_code}")
        print(f"  Overlap with biodiversity layer: {data['biodiversity_overlap_ha']:.2f} hectares")
        for key, value in data.items():
            if key.startswith('pa_overlap_ha_'):
                iucn_cat = key.replace('pa_overlap_ha_', '')
                print(f"  Overlap with protected areas (IUCN {iucn_cat}): {value:.2f} hectares")
            if key.startswith('bio_pa_overlap_ha_'):
                iucn_cat = key.replace('bio_pa_overlap_ha_', '')
                print(f"  Overlap with both biodiversity and protected areas (IUCN {iucn_cat}): {value:.2f} hectares")
        print()


if __name__ == "__main__":
    main()