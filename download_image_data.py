from concurrent.futures.thread import ThreadPoolExecutor

from infinitewisdom.config import Config
from infinitewisdom.persistence import ImageDataPersistence
from infinitewisdom.util import download_image_bytes

config = Config()

p = ImageDataPersistence(config)

added = 0
skipped = 0
deleted = 0
errored = 0
current = 0


def migrate_entity(executor, entity):
    global added
    global skipped
    global deleted
    global errored
    global current

    try:
        try:
            image_data = download_image_bytes(entity.url)
        except:
            print(
                "d Deleted: '{}'".format(
                    entity.url))
            p.delete(entity.url)
            deleted += 1
            return

        p.update(entity, image_data)
        print("+ Downloaded: '{}'".format(entity.url))
        added += 1
    except Exception as e:
        errored += 1
        print(e)
        executor.submit(migrate_entity, executor, entity)
    finally:
        current = added + deleted + skipped + errored
        print("Progress: {}/{}".format(current, total))


with ThreadPoolExecutor(max_workers=16, thread_name_prefix="db-migration") as executor:
    entities = p.find_without_image_data()
    total = len(entities)
    for e in entities:
        future = executor.submit(migrate_entity, executor, e)

print("Added {}/{} entries ({} skipped)".format(added, total, skipped))
