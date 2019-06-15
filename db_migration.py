from concurrent.futures.thread import ThreadPoolExecutor

from infinitewisdom.persistence.pickle import PicklePersistence
from infinitewisdom.persistence.sqlalchemy import SQLAlchemyPersistence

p1 = PicklePersistence(path="/var/infinite-wisdom/infinitewisdom.pickle")
p2 = SQLAlchemyPersistence()

p1_total = p1.count()
added = 0
skipped = 0
total = 0


def migrate_entity(entity):
    global added
    global skipped
    global total

    if len(p2.find_by_url(entity.url)) <= 0:
        print("Adding: {}".format(entity.url))
        p2.add(entity)
        added += 1
    else:
        print("Skipping: {}".format(entity.url))
        skipped += 1

    total = added + skipped
    print("Progress: {}/{}".format(total, p1_total))


with ThreadPoolExecutor(max_workers=4, thread_name_prefix="db-migration") as executor:
    for e in p1._entities:
        future = executor.submit(migrate_entity, e)

print("Added {}/{} entries ({} skipped)".format(added, total, skipped))
